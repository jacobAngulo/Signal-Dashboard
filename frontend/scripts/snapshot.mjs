import { chromium } from 'playwright'
import { writeFileSync, readFileSync } from 'fs'

const ROUTES = [
  ['overview',      '#/',                          'Overview — daily signal roll-up'],
  ['explore',       '#/explore',                   'Explore — filterable signal table'],
  ['analytics',     '#/analytics',                 'Analytics — charts + heatmap'],
  ['lstm-windows',  '#/lstm-windows',              'LSTM Windows — candidates, vectors, horizons'],
  ['scores',        '#/scores/lstm/2026-09-01',    'Scores — raw producer rows for one day'],
  ['ticker',        '#/ticker/AAPL',               'Ticker — one symbol, price chart + signals'],
  ['day',           '#/day/2026-09-01',            'Day — every signal for one trading day'],
  ['runs',          '#/runs',                      'Runs — producer run log'],
]

// Rows are the bulk of the file and every row past a handful is the same
// design problem restated. Keep enough to show striping, alignment and the
// widest realistic cell; drop the rest.
const KEEP_ROWS = 8

const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1380, height: 1000 } })
const sections = []

for (const [slug, hash, caption] of ROUTES) {
  await page.goto('http://localhost:5173/' + hash, { waitUntil: 'networkidle' })
  await page.reload({ waitUntil: 'networkidle' })
  await page.waitForTimeout(1200)
  const html = await page.evaluate((keep) => {
    const root = document.querySelector('#root')
    if (!root) return '<p>no root</p>'
    const clone = root.cloneNode(true)
    // Trim long tbodies.
    clone.querySelectorAll('tbody').forEach((tb) => {
      const rows = [...tb.querySelectorAll(':scope > tr')]
      if (rows.length <= keep) return
      rows.slice(keep).forEach((r) => r.remove())
      const cols = rows[0].children.length
      const note = document.createElement('tr')
      note.innerHTML = `<td colspan="${cols}" class="muted" style="text-align:center">
        &hellip; ${rows.length - keep} more rows trimmed from this snapshot</td>`
      tb.appendChild(note)
    })
    // recharts renders inline <svg> with absolute pixel geometry; it survives a
    // static copy fine, so it stays.
    return clone.innerHTML
  }, KEEP_ROWS)
  sections.push({ slug, caption, html })
  console.log(`captured ${slug} (${(html.length / 1024).toFixed(0)} KB)`)
}

await browser.close()

const css = readFileSync(new URL('../src/styles.css', import.meta.url).pathname, 'utf8')

const nav = sections.map((s) => `<a href="#snap-${s.slug}">${s.slug}</a>`).join('')

const out = `<!doctype html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Signal Dashboard — every screen, one page</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap">
<style>
/* ---- the app's real stylesheet, verbatim ---- */
${css}
/* ---- snapshot chrome only: not part of the app ---- */
.snap-bar { position: sticky; top: 0; z-index: 99; display: flex; flex-wrap: wrap; gap: 2px;
  padding: 8px 16px; background: var(--inset); border-bottom: 1px solid var(--rule-strong); }
.snap-bar a { font-family: var(--mono); font-size: 11px; text-transform: uppercase;
  letter-spacing: .1em; color: var(--muted); text-decoration: none; padding: 4px 10px; }
.snap-bar a:hover { color: var(--text); }
.snap-head { padding: 40px 16px 8px; border-top: 1px solid var(--rule-strong); margin-top: 32px; }
.snap-head:first-of-type { border-top: 0; margin-top: 0; }
.snap-head h2 { font-family: var(--mono); font-size: 12px; text-transform: uppercase;
  letter-spacing: .14em; color: var(--lstm-text); margin: 0 0 4px; }
.snap-head p { margin: 0; color: var(--muted); font-size: 13px; }
.snap-body { padding: 0 16px 8px; }
</style>
</head>
<body>
<nav class="snap-bar">${nav}</nav>
${sections.map((s) => `
<section class="snap-head" id="snap-${s.slug}">
  <h2>${s.slug}</h2>
  <p>${s.caption}</p>
</section>
<div class="snap-body">${s.html}</div>
`).join('\n')}
</body>
</html>
`

const dest = new URL('../../design/dashboard-snapshot.html', import.meta.url).pathname
writeFileSync(dest, out)
console.log('\nwrote ' + dest + '  ' + (out.length / 1024).toFixed(0) + ' KB')
