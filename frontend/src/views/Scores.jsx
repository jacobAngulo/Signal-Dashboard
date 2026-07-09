import React, { useEffect, useState } from 'react'
import { api, PRODUCER_META } from '../api.js'
import { fmtNum } from '../format.js'
import { href } from '../nav.js'
import { Card, ErrorBox, Spinner, TickerLink } from '../ui.jsx'

const PAGE = 100

// Server-side sorted/paginated browser over the raw daily score files.
// Route: #/scores or #/scores/<producer>/<date>
export default function Scores({ producer: p0, date: d0 }) {
  const [producer, setProducer] = useState(p0 || 'lstm')
  const [date, setDate] = useState(d0 || '')
  const [q, setQ] = useState('')
  const [sort, setSort] = useState(null)
  const [dir, setDir] = useState('desc')
  const [offset, setOffset] = useState(0)
  const [data, setData] = useState(null)
  const [err, setErr] = useState(null)

  useEffect(() => { setSort(null); setOffset(0) }, [producer])
  useEffect(() => { setOffset(0) }, [date, q])

  useEffect(() => {
    setErr(null)
    const load = async () => {
      let useDate = date
      if (!useDate) {
        const runs = await api('runs')
        const mine = runs.runs.filter((r) => r.producer === producer && r.has_scores)
        if (!mine.length) throw new Error(`no score files for ${producer}`)
        setDate(mine[0].date)
        return
      }
      const res = await api(`scores/${producer}/${useDate}`, { sort, dir, limit: PAGE, offset, q })
      setData(res)
      // keep the URL shareable without triggering a re-route
      history.replaceState(null, '', href('scores', producer, useDate))
    }
    load().catch(setErr)
  }, [producer, date, sort, dir, offset, q])

  const clickCol = (c) => {
    if (sort === c) setDir(dir === 'asc' ? 'desc' : 'asc')
    else { setSort(c); setDir('desc') }
    setOffset(0)
  }

  return (
    <div>
      <Card>
        <div className="filter-row">
          <select value={producer} onChange={(e) => { setProducer(e.target.value); setDate('') }}>
            {Object.entries(PRODUCER_META).map(([name, meta]) => (
              <option key={name} value={name}>{meta.label} scores</option>
            ))}
          </select>
          <select value={date} onChange={(e) => setDate(e.target.value)}>
            {(data?.dates || (date ? [date] : [])).slice().reverse().map((d) => (
              <option key={d} value={d}>{d}</option>
            ))}
          </select>
          <input placeholder="search ticker…" value={q} onChange={(e) => setQ(e.target.value)} style={{ width: 140 }} />
          {data && (
            <span className="muted" style={{ marginLeft: 'auto' }}>
              {data.total} rows · showing {Math.min(offset + 1, data.total)}–{Math.min(offset + PAGE, data.total)}
              <button className="btn" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>‹</button>
              <button className="btn" disabled={offset + PAGE >= data.total} onClick={() => setOffset(offset + PAGE)}>›</button>
            </span>
          )}
        </div>
      </Card>

      {err ? <ErrorBox err={err} /> : !data ? <Spinner /> : (
        <Card>
          <div className="table-wrap" style={{ maxHeight: '68vh', overflowY: 'auto' }}>
            <table>
              <thead>
                <tr>
                  {data.columns.map((c) => (
                    <th key={c} onClick={() => clickCol(c)} className={sort === c ? 'sorted' : ''}>
                      {c}{sort === c ? (dir === 'asc' ? ' ▲' : ' ▼') : ''}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.rows.map((r, i) => (
                  <tr key={i}>
                    {data.columns.map((c) => (
                      <td key={c}>
                        {c === 'ticker'
                          ? <TickerLink t={String(r[c]).toUpperCase()} bold={false} />
                          : typeof r[c] === 'number' ? fmtNum(r[c], 4) : r[c] === null ? '–' : String(r[c])}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  )
}
