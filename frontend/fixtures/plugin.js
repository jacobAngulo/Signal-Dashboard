// Serve recorded API responses to the dev server, in place of the backend.
//
// `npm run dev` proxies /api to a real dashboard on :8010, which only exists on
// the box that has the producer data. `npm run dev:fixtures` installs this
// instead: it answers from frontend/fixtures/api/, recorded by
// scripts/capture_api_fixtures.py. Same JSON, no backend, no sign-in.
//
// Matching is exact first, then a fallback to the same path's default capture.
// The fallback is the whole reason this is a plugin and not a static directory:
// a fixture set can record the views' opening requests, but it cannot enumerate
// every filter combination, and a 404 the moment someone touches a dropdown
// would make the fixtures useless for exactly the work they are meant for. A
// fallback response is real data for that endpoint that does not honour the
// filters -- so it says so, in a response header and in the terminal, rather
// than quietly pretending the filter worked.
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const API_DIR = path.join(HERE, 'api')
const INDEX = path.join(API_DIR, 'index.json')

// One canonical string per request, so a view's parameter order and the
// recorder's URL encoding cannot disagree. Empty values are dropped here for
// the same reason src/api.js drops them: they are never sent.
function canon(pathname, params) {
  const pairs = [...params.entries()]
    .filter(([, v]) => v !== '' && v !== null && v !== undefined)
    .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
    .map(([k, v]) => `${k}=${v}`)
  return pairs.length ? `${pathname}?${pairs.join('&')}` : pathname
}

function canonKey(key) {
  // Manifest keys are "GET /api/x?a=1&b=2" as written by the recorder.
  const withoutMethod = key.replace(/^[A-Z]+\s+/, '')
  const [pathname, search = ''] = withoutMethod.split('?')
  return canon(pathname, new URLSearchParams(search))
}

// Identity lookups must never fall back. Handing back a different signal than
// the row someone clicked is worse than an error: the panel fills in and looks
// right. List and aggregate endpoints are the opposite -- there, the recorded
// data with the wrong filters applied is still useful.
const EXACT_ONLY = new Set(['/api/signal'])

// The header search types a character at a time, so it asks for prefixes no
// recorder could enumerate. This is the one endpoint answered by computing
// rather than replaying: the same substring match and ranking as
// `Store.search_tickers` (backend/store.py:1195), over the union of every
// ticker the captures happen to mention.
function tickerIndex(records) {
  const seen = new Map()
  for (const record of records) {
    if (!record.key.startsWith('/api/tickers')) continue
    const payload = JSON.parse(
      fs.readFileSync(path.join(API_DIR, record.file), 'utf8'))
    for (const hit of payload.tickers || []) {
      if (!seen.has(hit.ticker)) seen.set(hit.ticker, hit)
    }
  }
  return [...seen.values()]
}

function searchTickers(index, q) {
  const qu = (q || '').toUpperCase().trim()
  if (!qu) return []
  return index
    .filter((e) => e.ticker.includes(qu))
    .sort((a, b) => (a.ticker.startsWith(qu) ? 0 : 1) - (b.ticker.startsWith(qu) ? 0 : 1)
      || b.n_signals - a.n_signals
      || (a.ticker < b.ticker ? -1 : 1))
    .slice(0, 15)
}

function loadManifest() {
  const manifest = JSON.parse(fs.readFileSync(INDEX, 'utf8'))
  const all = manifest.responses.map((r) => ({ ...r, key: canonKey(r.key) }))
  const exact = new Map()
  const byPath = new Map()
  for (const record of all) {
    exact.set(record.key, record)
    const pathname = record.key.split('?')[0]
    if (!byPath.has(pathname)) byPath.set(pathname, [])
    byPath.get(pathname).push(record)
  }
  // The default for a path is its least-parameterised capture: the request a
  // view makes when it first opens, before anyone has filtered anything.
  const fallback = new Map()
  for (const [pathname, records] of byPath) {
    const best = [...records].sort((a, b) => {
      const qa = (a.key.split('?')[1] || '').length
      const qb = (b.key.split('?')[1] || '').length
      return qa - qb || (a.file < b.file ? -1 : 1)
    })[0]
    fallback.set(pathname, best)
    fallback.set(pathname.toLowerCase(), best)
  }
  for (const pathname of EXACT_ONLY) {
    fallback.delete(pathname)
    fallback.delete(pathname.toLowerCase())
  }
  return { manifest, exact, fallback, tickers: tickerIndex(all) }
}

function send(res, status, body, headers = {}) {
  res.statusCode = status
  res.setHeader('Content-Type', 'application/json')
  for (const [k, v] of Object.entries(headers)) res.setHeader(k, v)
  res.end(body)
}

export function apiFixtures({ delayMs = 0 } = {}) {
  let state = null
  let indexMtime = 0

  const refresh = () => {
    const mtime = fs.statSync(INDEX).mtimeMs
    if (!state || mtime !== indexMtime) {
      state = loadManifest()
      indexMtime = mtime
    }
    return state
  }

  return {
    name: 'signal-dashboard-api-fixtures',
    configureServer(server) {
      if (!fs.existsSync(INDEX)) {
        server.config.logger.error(
          `[fixtures] ${INDEX} is missing. Re-record it on the data box with\n` +
          '           .venv/bin/python scripts/capture_api_fixtures.py',
        )
        return
      }
      const { manifest } = refresh()
      server.config.logger.info(
        `[fixtures] serving ${manifest.counts.responses} recorded responses ` +
        `(${manifest.window.from}..${manifest.window.to}, ` +
        `captured ${manifest.captured_at})`,
      )

      server.middlewares.use((req, res, next) => {
        if (!req.url?.startsWith('/api/')) return next()
        const { exact, fallback, tickers } = refresh()
        const url = new URL(req.url, 'http://fixtures.local')

        // The feedback widget posts to Ticket Board through the backend. There
        // is nothing to record and nothing to relay, so acknowledge it the way
        // the real relay does and let the widget show its receipt.
        if (req.method === 'POST' && url.pathname === '/api/feedback') {
          return send(res, 200, JSON.stringify({
            identifier: 'TB-000', id: 0, status: 'backlog',
            title: 'Recorded locally (fixtures mode)',
          }))
        }
        if (req.method !== 'GET') return next()

        if (url.pathname === '/api/tickers') {
          return send(res, 200, JSON.stringify({
            tickers: searchTickers(tickers, url.searchParams.get('q')),
          }), { 'x-fixture-match': 'computed' })
        }

        const key = canon(url.pathname, url.searchParams)
        const hit = exact.get(key)
        const record = hit
          || fallback.get(url.pathname)
          || fallback.get(url.pathname.toLowerCase())

        if (!record) {
          server.config.logger.warn(`[fixtures] no capture for ${req.url}`)
          const detail = EXACT_ONLY.has(url.pathname)
            // Recorded by id, from the rows the recorded lists contain. Rows
            // further down a list than the recorder went have no detail, and
            // showing a neighbour's would be a lie the panel renders happily.
            ? `${url.pathname} is recorded per id and this one was not captured. `
              + 'Raise --signals on scripts/capture_api_fixtures.py to cover more rows.'
            : `No fixture recorded for ${url.pathname}. `
              + 'Add it to list_specs() in scripts/capture_api_fixtures.py '
              + 'and re-record on the data box.'
          return send(res, 404, JSON.stringify({ detail }),
            { 'x-fixture-match': 'miss' })
        }

        if (!hit) {
          server.config.logger.info(
            `[fixtures] ${req.url}\n           -> ${record.file} ` +
            '(closest capture; its filters are the recorded ones, not yours)',
          )
        }

        const body = fs.readFileSync(path.join(API_DIR, record.file))
        const respond = () => send(res, record.status, body, {
          'x-fixture-match': hit ? 'exact' : 'fallback',
          'x-fixture-file': record.file,
        })
        if (delayMs > 0) setTimeout(respond, delayMs)
        else respond()
      })
    },
  }
}
