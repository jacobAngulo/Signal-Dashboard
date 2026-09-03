import React, { useEffect, useMemo, useState } from 'react'
import { api, PRODUCER_META } from '../api.js'
import { fmtAgo, fmtPct, fmtTime, fmtTs } from '../format.js'
import { href } from '../nav.js'
import { DateLink, ErrorBox, ProducerTag, Spinner, StatusTag, Tag } from '../ui.jsx'
import Heatmap from '../Heatmap.jsx'
import SignalTable from '../SignalTable.jsx'
import SignalDetail from '../SignalDetail.jsx'

// Design turn 3b, "triage queue": signals own the top fold, split into what
// there is nothing to judge yet (act or wait) and what has a return, and run
// health moves to a rail where it is glanceable without being in the way.
const OVERVIEW_COLS = [
  'when', 'ticker', 'call', 'metric', 'entry',
  'ret_1d', 'ret_5d', 'ret_20d', 'since', 'since_bar', 'exit',
]

export default function Overview() {
  const [data, setData] = useState(null)
  const [err, setErr] = useState(null)
  const [sel, setSel] = useState(null)
  const [producer, setProducer] = useState('')

  const load = () => api('overview')
    .then((next) => { setData(next); setErr(null) })
    .catch(setErr)
  useEffect(() => {
    load()
    const t = setInterval(load, 60000)
    return () => clearInterval(t)
  }, [])

  const rows = useMemo(
    () => (data?.latest_signals || []).filter((r) => !producer || r.producer === producer),
    [data, producer],
  )
  // "Unsettled" is not a status, it is the absence of one: no scored close
  // since the signal, or no price coverage at all. Either way there is
  // nothing to judge, so it leads the queue instead of hiding mid-table.
  const sections = useMemo(() => [
    {
      key: 'unsettled', label: 'Unsettled',
      note: 'no scored close yet, or no price coverage',
      rows: rows.filter((r) => r.ret_since == null),
    },
    {
      key: 'tracked', label: 'Tracked', note: 'scored against entry',
      rows: rows.filter((r) => r.ret_since != null),
    },
  ], [rows])

  if (err && !data) return <ErrorBox err={err} />
  if (!data) return <Spinner />

  const allTime = Object.values(data.producers)
    .reduce((total, p) => total + (p.totals?.signals || 0), 0)
  const newest = data.latest_signals.filter((r) => r.date === data.latest_date).length

  return (
    <div className="triage">
      {err && <ErrorBox err={err} />}

      <div className="triage-body">
        <div className="triage-main">
          <div className="ledger-head">
            <div>
              <h1 tabIndex="-1">Buy signals</h1>
              <div className="ledger-meta">
                {allTime.toLocaleString()} all time · {data.latest_signals.length} most recent
                {data.latest_date ? ` · ${newest} on ${data.latest_date}` : ''}
              </div>
            </div>
            <div className="seg" role="group" aria-label="Filter by producer">
              {[['', 'All'], ...Object.entries(PRODUCER_META).map(([k, m]) => [k, m.label])]
                .map(([value, label]) => (
                  <button key={value || 'all'} type="button"
                          className={`seg-btn ${producer === value ? 'active' : ''}`}
                          aria-pressed={producer === value}
                          onClick={() => setProducer(value)}>{label}</button>
                ))}
            </div>
            <a className="dlink ledger-more" href={href('explore')}>explore all →</a>
          </div>

          <SignalTable rows={rows} sections={sections} cols={OVERVIEW_COLS}
                       onRow={setSel} empty="No BUY signals yet" />
        </div>

        <aside className="triage-rail">
          <section className="rail-card">
            <h2 className="card-title">Producer runs</h2>
            <div className="rail-runs">
              {Object.entries(data.producers).map(([name, p]) => (
                <RunRow key={name} name={name} p={p} />
              ))}
            </div>
          </section>

          <section className="rail-card">
            <div className="rail-head">
              <h2 className="card-title">Run calendar</h2>
              <a className="dlink" href={href('runs')}>log →</a>
            </div>
            <Heatmap calendar={data.calendar} />
          </section>
        </aside>
      </div>

      <SignalDetail signal={sel} onClose={() => setSel(null)} />
    </div>
  )
}

// One producer's run health as three numbers and a sentence, not a card: the
// matrix reads down the column (scores, buys, 5d win) across all three.
function RunRow({ name, p }) {
  const run = p.latest_run
  const pipe = p.pipeline
  const totals = p.totals || {}
  if (!run) {
    return (
      <div className="rail-run">
        <div className="rail-run-head"><ProducerTag producer={name} /></div>
        <div className="muted small">no runs found</div>
      </div>
    )
  }
  // Market-day boundary is ET: after the 16:00 ET close, foundry events roll
  // to the next session, so the row can legitimately show tomorrow's date.
  const todayET = new Date().toLocaleDateString('en-CA', { timeZone: 'America/New_York' })
  const nextSession = pipe && run.date > todayET
  const winSub = totals.n_measurable === 0
    ? 'no measurable buys yet'
    : totals.avg_5d == null ? null : `avg ${fmtPct(totals.avg_5d)} · n=${totals.n_measurable}`
  return (
    <div className="rail-run">
      <div className="rail-run-head">
        <ProducerTag producer={name} />
        <DateLink d={run.date} />
        <StatusTag status={run.status} title={run.failure_reason} />
      </div>
      <div className="rail-run-cells">
        <Cell label={pipe ? 'events' : 'scores'}
              v={(pipe ? run.n_events ?? run.n_scores : run.n_scores)?.toLocaleString() ?? '–'} />
        <Cell label="buys" v={run.n_buy} cls={run.n_buy > 0 ? 'pos' : ''} />
        <Cell label="5d win" v={totals.win_5d == null ? '–' : fmtPct(totals.win_5d, 0)} />
      </div>
      <div className="rail-run-note muted small">
        {winSub ? `${winSub} · ` : ''}
        {pipe
          ? `${run.n_decisions} tickers · ${(totals.events || 0).toLocaleString()} ev / ${totals.days} d`
          : `${totals.signals} sig / ${totals.days} d`}
        {run.generated_at ? ` · gen ${fmtTime(run.generated_at)}` : ''}
        {nextSession ? ' · next session — after-close events'
          : run.as_of_date ? ` · as of close ${run.as_of_date}` : ''}
        {run.decision_summary && run.n_buy === 0 ? ` · ${run.decision_summary}` : ''}
      </div>
      {pipe && <PipelineRow pipe={pipe} />}
    </div>
  )
}

function Cell({ label, v, cls }) {
  return (
    <div className="rail-cell">
      <div className="stat-label">{label}</div>
      <div className={`rail-cell-v ${cls || ''}`}>{v}</div>
    </div>
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
    <div className="rail-pipe">
      <div className="muted small">
        queue {pipe.pending ?? '–'}
        {pipe.benched > 0 ? ` · ${pipe.benched} benched` : ''}
        {' · fetched '}{fmtAgo(pipe.last_fetch)} ago
      </div>
      <div className="pipe-srcs">
        {(pipe.sources || []).map((s) => (
          <Tag key={s.source} kind={ageKind(s.last_published)}
               title={`${s.source}: ${s.items} items · newest ${fmtTs(s.last_published)} · fetched ${fmtTs(s.last_fetched)}`}>
            {SRC_LABEL[s.source] || s.source} {fmtAgo(s.last_published)}
          </Tag>
        ))}
      </div>
    </div>
  )
}
