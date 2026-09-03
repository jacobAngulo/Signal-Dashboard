import { chromium } from 'playwright'
import { writeFileSync, readFileSync } from 'fs'

// The fixture dev server by default. `/api/lab` has no recorded capture yet, so
// a box without one has to point this at something that answers it -- hence the
// override rather than a hardcoded port.
const BASE = process.env.SNAPSHOT_BASE || 'http://localhost:5173'

// Route-level compositions. One entry per screen the router can land on.
const SCREENS = [
  ['overview',     '#/',                       'Overview — daily signal roll-up'],
  ['explore',      '#/explore',                'Explore — filterable signal ledger'],
  ['analytics',    '#/analytics',              'Analytics — performance charts and heatmaps'],
  ['lab',          '#/lab/lstm',               'Lab — free-form slicing across every vector'],
  ['lab-curated',  '#/lab/lstm/curated',       'Lab (curated) — one named vector at a time, fixed bucketing'],
  ['scores',       '#/scores/lstm/2026-09-01', 'Scores — raw producer rows for one date'],
  ['ticker',       '#/ticker/AAPL',            'Ticker — one symbol, its chart, scores, and signals'],
  ['day',          '#/day/2026-09-01',         'Day — all producer output for one trading day'],
  ['runs',         '#/runs',                   'Runs — producer run history'],
]

// States are captured by driving the real UI, not by patching the screen HTML
// afterwards. A regex that rewrites markup drifts silently the moment a
// component changes; a click that finds no element fails loudly here.
const clickFirst = (selector) => async (page) => {
  const target = page.locator(selector).first()
  await target.waitFor({ state: 'visible', timeout: 15000 })
  await target.click()
}

const STATES = [
  ['ticker-search-populated', '#/', 'Global ticker search with an open result list',
    async (page) => {
      const box = page.locator('.search-box input').first()
      await box.click()
      await box.fill('AAPL')
      await page.waitForSelector('.search-drop', { timeout: 15000 })
    }],
  ['signal-detail-drawer', '#/day/2026-09-01', 'Signal detail drawer over the day view',
    async (page) => {
      await clickFirst('tbody tr.clickable')(page)
      await page.waitForSelector('.drawer-overlay', { timeout: 15000 })
    }],
  ['signal-inspector', '#/explore', 'Docked signal inspector beside the explore ledger',
    async (page) => {
      await clickFirst('tbody tr.clickable')(page)
      await page.waitForSelector('.inspector', { timeout: 15000 })
    }],
  ['feedback-panel', '#/', 'Feedback form over its page context',
    async (page) => {
      await clickFirst('.feedback-launcher')(page)
      await page.waitForSelector('.feedback-panel', { timeout: 15000 })
    }],
  ['lab-filtered', '#/lab/lstm', 'Lab with several vectors constrained: touched facets, active filter strip, filtered result cards',
    async (page) => {
      // A numeric bound and a category exclusion, because the rail renders the
      // two facet kinds differently and both belong in the artifact.
      const bound = page.locator('.facet .facet-bounds input[type="number"]').first()
      await bound.waitFor({ state: 'visible', timeout: 20000 })
      await bound.fill('0.55')
      await bound.press('Enter')
      const chip = page.locator('.facet-chips button').first()
      if (await chip.count()) await chip.click()
      await page.waitForSelector('.rail-active .chip-active', { timeout: 15000 })
      await page.waitForTimeout(600)
    }],
  ['lab-undefined-producer', '#/lab/intrinsic', 'Lab pointed at a producer with no row set defined yet',
    async (page) => { await page.waitForTimeout(400) }],
]

// Rows are the bulk of the file and every row past a handful is the same
// design problem restated. Keep enough to show striping, alignment and the
// widest realistic cell; drop the rest.
const KEEP_ROWS = 8

const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1380, height: 1000 } })
const sections = []

const grab = () => page.evaluate((keep) => {
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
  // A live <input>'s typed text lives in the property, not the attribute, so a
  // cloned search box would come back empty without this.
  clone.querySelectorAll('input').forEach((el, i) => {
    const live = root.querySelectorAll('input')[i]
    if (!live) return
    if (live.type === 'checkbox' || live.type === 'radio') {
      if (live.checked) el.setAttribute('checked', '')
      else el.removeAttribute('checked')
    } else if (live.value !== '') el.setAttribute('value', live.value)
  })
  // recharts renders inline <svg> with absolute pixel geometry; it survives a
  // static copy fine, so it stays.
  return clone.innerHTML
}, KEEP_ROWS)

async function visit(hash) {
  await page.goto(BASE + '/' + hash, { waitUntil: 'networkidle' })
  await page.reload({ waitUntil: 'networkidle' })
  await page.waitForTimeout(1200)
}

for (const [slug, hash, caption] of SCREENS) {
  await visit(hash)
  const html = await grab()
  sections.push({ slug, caption, kind: 'screen', html })
  console.log(`captured screen ${slug} (${(html.length / 1024).toFixed(0)} KB)`)
}

for (const [slug, hash, caption, act] of STATES) {
  await visit(hash)
  await act(page)
  const html = await grab()
  sections.push({ slug, caption, kind: 'state', html })
  console.log(`captured state  ${slug} (${(html.length / 1024).toFixed(0)} KB)`)
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
<section class="snap-head" id="snap-${s.slug}" data-kind="${s.kind}">
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
