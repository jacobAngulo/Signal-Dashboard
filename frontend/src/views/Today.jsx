import React, { useEffect, useState } from 'react'
import { api, PRODUCER_META } from '../api.js'
import { fmtNum, fmtPct, fmtPx, fmtTs } from '../format.js'
import { Card, ErrorBox, Pct, ProducerTag, Spinner, Stat, StateTag, StatusTag, Table, Tag } from '../ui.jsx'
import SignalDetail from '../SignalDetail.jsx'

export default function Today() {
  const [data, setData] = useState(null)
  const [err, setErr] = useState(null)
  const [sel, setSel] = useState(null)

  const load = () => api('summary').then(setData).catch(setErr)
  useEffect(() => {
    load()
    const t = setInterval(load, 60000)
    return () => clearInterval(t)
  }, [])

  if (err) return <ErrorBox err={err} />
  if (!data) return <Spinner />

  const allLatest = Object.values(data.producers).flatMap((p) => p.latest_decisions)

  return (
    <div>
      <div className="grid-2">
        {Object.entries(data.producers).map(([name, p]) => (
          <ProducerCard key={name} name={name} p={p} />
        ))}
      </div>

      <Card
        title={`Latest decisions (${data.latest_date || 'n/a'})`}
        right={<span className="muted">{allLatest.length} rows · click a row for detail</span>}
      >
        <DecisionTable rows={allLatest} onRow={setSel} />
      </Card>

      <SignalDetail signal={sel} onClose={() => setSel(null)} />
    </div>
  )
}

function ProducerCard({ name, p }) {
  const run = p.latest_run
  return (
    <Card
      title={<span><ProducerTag producer={name} /> <span className="muted">latest run</span></span>}
      right={run ? <StatusTag status={run.status} /> : null}
    >
      {!run ? (
        <div className="muted">no runs found</div>
      ) : (
        <>
          <div className="stat-row">
            <Stat label="trade date" value={run.date} sub={run.as_of_date ? `as of ${run.as_of_date}` : null} />
            <Stat label="scores" value={run.n_scores ?? '–'} sub={run.stale ? `${run.stale} stale` : null} />
            <Stat label="decisions" value={run.n_buy} sub={run.decision_summary || null} />
            <Stat label="generated" value={run.generated_at ? fmtTs(run.generated_at) : '–'} />
          </div>
          <div className="stat-row" style={{ marginTop: 8 }}>
            <Stat label="days tracked" value={p.totals.days} />
            <Stat label="signals all-time" value={p.totals.signals} />
            <Stat label="traded by bots" value={p.totals.traded} />
          </div>
          <div className="run-strip">
            {p.recent_runs.slice().reverse().map((r) => (
              <span key={r.date} title={`${r.date}: ${r.status || 'no status'} · ${r.n_buy} buys`}
                    className={`run-dot ${r.status === 'ok' ? 'ok' : r.status ? 'err' : 'na'} ${r.n_buy ? 'has-buy' : ''}`} />
            ))}
            <span className="muted" style={{ marginLeft: 8 }}>last {p.recent_runs.length} runs (dot = day, ring = had buys)</span>
          </div>
        </>
      )}
    </Card>
  )
}

export function DecisionTable({ rows, onRow }) {
  return (
    <Table
      onRow={onRow}
      rows={rows}
      initSort="date"
      empty="No decisions on the latest run — check Runs for history"
      columns={[
        { key: 'date', label: 'Date' },
        { key: 'producer', label: 'Producer', render: (r) => <ProducerTag producer={r.producer} /> },
        { key: 'ticker', label: 'Ticker', render: (r) => <b>{r.ticker}</b> },
        { key: 'decision', label: 'Decision', render: (r) => <Tag kind={r.decision === 'BUY' ? 'ok' : 'muted'}>{r.decision}</Tag> },
        {
          key: 'metric', label: 'Signal metric', align: 'right',
          title: 'LSTM: adjusted probability · Intrinsic: discount to intrinsic value',
          render: (r) => (
            <span>
              {fmtNum(r.metric, 3)} <span className="muted">{PRODUCER_META[r.producer]?.metric}</span>
              {r.horizon ? <span className="muted"> · {r.horizon}</span> : null}
            </span>
          ),
        },
        { key: 'entry_px', label: 'Entry', align: 'right', render: (r) => fmtPx(r.entry_px) },
        { key: 'ret_1d', label: '1d', align: 'right', render: (r) => <Pct v={r.ret_1d} /> },
        { key: 'ret_5d', label: '5d', align: 'right', render: (r) => <Pct v={r.ret_5d} /> },
        { key: 'ret_since', label: 'Since', align: 'right', render: (r) => <Pct v={r.ret_since} /> },
        { key: 'state', label: 'Status', render: (r) => <StateTag state={r.state} /> },
        {
          key: 'bots', label: 'Bots', sortVal: (r) => r.exec?.n_bots || 0,
          render: (r) => (r.exec?.traded ? <span title={(r.exec.bots || []).join(', ')}>{r.exec.n_bots} bot{r.exec.n_bots > 1 ? 's' : ''}</span> : <span className="muted">–</span>),
        },
      ]}
    />
  )
}
