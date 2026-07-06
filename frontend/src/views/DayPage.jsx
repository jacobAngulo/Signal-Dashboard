import React, { useEffect, useState } from 'react'
import { api } from '../api.js'
import { fmtNum, fmtPx } from '../format.js'
import { href } from '../nav.js'
import { Card, ErrorBox, ProducerTag, Spinner, StatusTag, Table, Tag, TickerLink } from '../ui.jsx'
import SignalTable from '../SignalTable.jsx'
import SignalDetail from '../SignalDetail.jsx'

// One trade date: what each producer generated, with what, and the decisions.
export default function DayPage({ date }) {
  const [data, setData] = useState(null)
  const [err, setErr] = useState(null)
  const [sel, setSel] = useState(null)

  useEffect(() => {
    setData(null); setErr(null)
    api(`day/${date}`).then(setData).catch(setErr)
  }, [date])

  if (err) return <ErrorBox err={err} />
  if (!data) return <Spinner />

  return (
    <div>
      <div className="crumb">
        {data.prev ? <a className="dlink" href={href('day', data.prev)}>‹ {data.prev}</a> : <span />}
        <span className="crumb-title">{data.date}</span>
        {data.next ? <a className="dlink" href={href('day', data.next)}>{data.next} ›</a> : <span />}
      </div>

      {Object.entries(data.producers).map(([name, p]) => (
        <Card
          key={name}
          title={<span><ProducerTag producer={name} /> {p.run ? <StatusTag status={p.run.status} /> : <Tag kind="muted">no run</Tag>}</span>}
          right={p.scores_available && (
            <a className="dlink" href={href('scores', name, data.date)}>
              browse all {p.n_scores} scores →
            </a>
          )}
        >
          {p.status_raw && (
            <div className="kv-grid small">
              {Object.entries(p.status_raw)
                .filter(([k, v]) => !k.startsWith('_') && typeof v !== 'object')
                .map(([k, v]) => (
                  <React.Fragment key={k}><span>{k}</span><b>{String(v)}</b></React.Fragment>
                ))}
            </div>
          )}

          <h4 className="section-h">Decisions</h4>
          {p.decisions.length > 0
            ? <SignalTable rows={p.decisions} onRow={setSel} hide={['date', 'producer']} />
            : <div className="muted" style={{ padding: '4px 0 10px' }}>no decision rows for this date</div>}

          {p.top_scores.length > 0 && (
            <>
              <h4 className="section-h">Top of the score file (by {p.metric_col})</h4>
              <Table
                rows={p.top_scores.map((r, i) => ({ ...r, key: i }))}
                columns={[
                  { key: 'ticker', label: 'Ticker', render: (r) => <TickerLink t={String(r.ticker).toUpperCase()} /> },
                  { key: p.metric_col, label: p.metric_col, align: 'right', render: (r) => fmtNum(r[p.metric_col], 4) },
                  ...(name === 'lstm'
                    ? [
                        { key: 'best_horizon', label: 'Horizon' },
                        { key: 'close', label: 'Close', align: 'right', render: (r) => fmtPx(r.close) },
                      ]
                    : [
                        { key: 'price', label: 'Price', align: 'right', render: (r) => fmtPx(r.price) },
                        { key: 'intrinsic_value', label: 'Intrinsic', align: 'right', render: (r) => fmtNum(r.intrinsic_value, 2) },
                        { key: 'status', label: 'Status' },
                      ]),
                ]}
              />
            </>
          )}
        </Card>
      ))}

      <SignalDetail signal={sel} onClose={() => setSel(null)} />
    </div>
  )
}
