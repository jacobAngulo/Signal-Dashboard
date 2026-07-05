import React, { useEffect, useState } from 'react'
import { api } from '../api.js'
import { fmtNum } from '../format.js'
import { Card, ErrorBox, Spinner } from '../ui.jsx'

const PAGE = 100

// Server-side sorted/paginated browser over the full daily score files.
export default function Scores({ initial }) {
  const [producer, setProducer] = useState(initial?.producer || 'lstm')
  const [date, setDate] = useState(initial?.date || '')
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
    const d = date || 'latest'
    const load = async () => {
      let useDate = date
      if (!useDate) {
        // resolve latest available date for the producer via the runs list
        const runs = await api('runs')
        const mine = runs.runs.filter((r) => r.producer === producer && r.has_scores)
        if (!mine.length) throw new Error(`no score files for ${producer}`)
        useDate = mine[0].date
        setDate(useDate)
        return // state change re-triggers
      }
      const res = await api(`scores/${producer}/${useDate}`, { sort, dir, limit: PAGE, offset, q })
      setData(res)
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
            <option value="lstm">LSTM scores</option>
            <option value="intrinsic">Intrinsic scores</option>
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
          <div className="table-wrap" style={{ maxHeight: '65vh', overflowY: 'auto' }}>
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
                        {typeof r[c] === 'number' ? fmtNum(r[c], 4) : r[c] === null ? '–' : String(r[c])}
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
