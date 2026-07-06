import React, { useEffect, useState } from 'react'
import { api } from '../api.js'
import { fmtPct, fmtTs } from '../format.js'
import { href } from '../nav.js'
import { Card, DateLink, ErrorBox, Pct, PerfTag, ProducerTag, Spinner, Stat, StatusTag, TickerLink } from '../ui.jsx'
import Heatmap from '../Heatmap.jsx'
import SignalTable from '../SignalTable.jsx'
import SignalDetail from '../SignalDetail.jsx'

export default function Overview() {
  const [data, setData] = useState(null)
  const [err, setErr] = useState(null)
  const [sel, setSel] = useState(null)

  const load = () => api('overview').then(setData).catch(setErr)
  useEffect(() => {
    load()
    const t = setInterval(load, 60000)
    return () => clearInterval(t)
  }, [])

  if (err) return <ErrorBox err={err} />
  if (!data) return <Spinner />

  return (
    <div>
      <div className="grid-2">
        {Object.entries(data.producers).map(([name, p]) => (
          <ProducerCard key={name} name={name} p={p} />
        ))}
      </div>

      <Card title="Run calendar" right={<a className="dlink" href={href('runs')}>full run log →</a>}>
        <Heatmap calendar={data.calendar} />
      </Card>

      <div className="grid-31">
        <Card
          title={`Recent signals (latest first)`}
          right={<a className="dlink" href={href('explore')}>explore all →</a>}
        >
          <SignalTable rows={data.latest_signals} onRow={setSel} maxHeight="52vh"
                       empty="No signals yet" />
        </Card>
        <div>
          <Card title="Best since signal">
            <MoverList rows={data.recent.best} />
          </Card>
          <Card title="Worst since signal">
            <MoverList rows={data.recent.worst} />
          </Card>
        </div>
      </div>

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
        <div className="stat-row">
          <Stat label="trade date" value={<DateLink d={run.date} />}
                sub={run.as_of_date ? `as of close ${run.as_of_date}` : null} />
          <Stat label="scores" value={run.n_scores ?? '–'}
                sub={run.stale ? `${run.stale} stale rows` : 'fresh'} />
          <Stat label="buys" value={run.n_buy}
                sub={run.decision_summary && run.n_buy === 0 ? run.decision_summary : null}
                cls={run.n_buy > 0 ? 'pos' : ''} />
          <Stat label="generated" value={run.generated_at ? fmtTs(run.generated_at) : '–'} />
          <Stat label="all-time" value={`${p.totals.signals} signals`}
                sub={`${p.totals.days} run days`} />
          <Stat label="5d win rate" value={p.totals.win_5d === null ? '–' : fmtPct(p.totals.win_5d, 0)}
                sub={p.totals.avg_5d === null ? null : `avg ${fmtPct(p.totals.avg_5d)}`}
                cls={p.totals.avg_5d > 0 ? 'pos' : p.totals.avg_5d < 0 ? 'neg' : ''} />
        </div>
      )}
    </Card>
  )
}

function MoverList({ rows }) {
  if (!rows.length) return <div className="muted">nothing tracked yet</div>
  return (
    <div className="mover-list">
      {rows.map((r, i) => (
        <div key={i} className="mover">
          <TickerLink t={r.ticker} />
          <ProducerTag producer={r.producer} />
          <DateLink d={r.date} />
          <span style={{ marginLeft: 'auto' }}><Pct v={r.ret_since} /></span>
        </div>
      ))}
    </div>
  )
}
