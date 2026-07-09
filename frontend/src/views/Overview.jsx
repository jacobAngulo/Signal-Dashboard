import React, { useEffect, useState } from 'react'
import { api } from '../api.js'
import { fmtAgo, fmtPct, fmtTs } from '../format.js'
import { href } from '../nav.js'
import { Card, DateLink, ErrorBox, Pct, PerfTag, ProducerTag, Spinner, Stat, StatusTag, Tag, TickerLink } from '../ui.jsx'
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
  const pipe = p.pipeline
  // Market-day boundary is ET: after the 16:00 ET close, foundry events roll
  // to the next session, so the card can legitimately show tomorrow's date.
  const todayET = new Date().toLocaleDateString('en-CA', { timeZone: 'America/New_York' })
  const nextSession = pipe && run && run.date > todayET
  const winSub = p.totals.n_measurable === 0
    ? 'no measurable buys yet'
    : p.totals.avg_5d === null ? null : `avg ${fmtPct(p.totals.avg_5d)} · n=${p.totals.n_measurable}`
  return (
    <Card
      title={<span><ProducerTag producer={name} /> <span className="muted">{pipe ? 'event stream' : 'latest run'}</span></span>}
      right={run ? <StatusTag status={run.status} /> : null}
    >
      {!run ? (
        <div className="muted">no runs found</div>
      ) : (
        <div className="stat-row">
          <Stat label="trade date" value={<DateLink d={run.date} />}
                sub={nextSession ? 'next session — after-close events'
                     : run.as_of_date ? `as of close ${run.as_of_date}` : null} />
          {pipe
            ? <Stat label="events" value={run.n_events ?? run.n_scores ?? '–'}
                    sub={`${run.n_decisions} tickers`} />
            : <Stat label="scores" value={run.n_scores ?? '–'}
                    sub={run.stale ? `${run.stale} stale rows` : 'fresh'} />}
          <Stat label="buys" value={run.n_buy}
                sub={run.decision_summary && run.n_buy === 0 ? run.decision_summary : null}
                cls={run.n_buy > 0 ? 'pos' : ''} />
          <Stat label={pipe ? 'last extracted' : 'generated'}
                value={run.generated_at ? fmtTs(run.generated_at) : '–'} />
          <Stat label="all-time"
                value={pipe ? `${p.totals.events} events` : `${p.totals.signals} signals`}
                sub={pipe ? `${p.totals.signals} buys · ${p.totals.days} days` : `${p.totals.days} run days`} />
          <Stat label="5d win rate" value={p.totals.win_5d === null ? '–' : fmtPct(p.totals.win_5d, 0)}
                sub={winSub}
                cls={p.totals.avg_5d > 0 ? 'pos' : p.totals.avg_5d < 0 ? 'neg' : ''} />
        </div>
      )}
      {pipe && <PipelineRow pipe={pipe} />}
    </Card>
  )
}

const SRC_LABEL = { sec_edgar: 'edgar', hackernews: 'hn', stocktwits: 'stocktwits' }

// Freshness per source: an event producer with a silent source looks exactly
// like a quiet news day unless the staleness is shown outright.
function PipelineRow({ pipe }) {
  const ageKind = (iso) => {
    if (!iso) return 'err'
    const h = (Date.now() - new Date(iso).getTime()) / 3600000
    return h <= 2 ? 'ok' : h <= 24 ? 'warn' : 'err'
  }
  return (
    <div className="pipe-row">
      <span className="muted small">
        queue {pipe.pending ?? '–'}
        {pipe.benched > 0 ? ` · ${pipe.benched} benched` : ''}
        {' · fetched '}{fmtAgo(pipe.last_fetch)} ago
      </span>
      <span className="pipe-srcs">
        {(pipe.sources || []).map((s) => (
          <Tag key={s.source} kind={ageKind(s.last_published)}
               title={`${s.source}: ${s.items} items · newest ${fmtTs(s.last_published)} · fetched ${fmtTs(s.last_fetched)}`}>
            {SRC_LABEL[s.source] || s.source} {fmtAgo(s.last_published)}
          </Tag>
        ))}
      </span>
    </div>
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
