import { mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const designDir = dirname(here)
const repoDir = dirname(designDir)
const snapshot = readFileSync(join(designDir, 'dashboard-snapshot.html'), 'utf8')

// The inventory. Every entry is a section the snapshot actually captured from
// the running app -- states included, so nothing here is reconstructed by
// rewriting another artifact's markup.
const screens = [
  ['overview', 'Overview', 'Daily buy-signal roll-up and the coverage calendar'],
  ['explore', 'Explore', 'Filterable signal ledger'],
  ['analytics', 'Analytics', 'Signal performance: hit rates, return distributions, and per-producer meters'],
  ['lab', 'Lab', 'Free-form slicing across every vector'],
  ['lab-curated', 'Lab · curated', 'The former LSTM Windows tab, now a view inside the lab'],
  ['scores', 'Scores', 'Raw producer rows for one date'],
  ['ticker', 'Ticker', 'One symbol, its chart, scores, and signals'],
  ['day', 'Day', 'All producer output for one trading day'],
  ['runs', 'Runs', 'Producer run history and its calendar heatmap'],
]

const states = [
  ['ticker-search-populated', 'Populated ticker search', 'Global search with an open result list'],
  ['signal-detail-drawer', 'Signal detail drawer', 'Modal drawer over the day view'],
  ['signal-inspector', 'Docked signal inspector', 'Explore with a selected signal'],
  ['feedback-panel', 'Feedback panel', 'Issue form over its page context'],
  ['lab-filtered', 'Lab · filtered', 'Touched facets, the active filter strip, and filtered result cards'],
  ['lab-undefined-producer', 'Lab · undefined producer', 'A producer with no row set defined yet'],
]

const sectionPattern = /<section class="snap-head" id="snap-([^"]+)"[^>]*><h2>[^<]*<\/h2><p>([^<]*)<\/p><\/section><div class="snap-body">([\s\S]*?)<\/div>(?=<section class="snap-head" id="snap-|<\/body>)/g
const captured = new Map([...snapshot.matchAll(sectionPattern)].map((m) => [m[1], m[3]]))
const missing = [...screens, ...states].map(([slug]) => slug).filter((slug) => !captured.has(slug))
if (missing.length) throw new Error(`Snapshot is missing catalog artifacts: ${missing.join(', ')}`)

mkdirSync(join(here, 'assets'), { recursive: true })
for (const dir of ['screens', 'states']) {
  // Written fresh every build, so a removed screen leaves no orphan behind.
  rmSync(join(here, dir), { recursive: true, force: true })
  mkdirSync(join(here, dir), { recursive: true })
}
const appCss = readFileSync(join(repoDir, 'frontend', 'src', 'styles.css'), 'utf8')
writeFileSync(join(here, 'assets', 'app.css'), `${appCss.trim()}\n`)

// Frontend navigation, mapped onto static files. Longest prefix first so
// `#/lab/lstm/curated` does not get swallowed by `#/lab`.
const routes = [
  ['/lab/lstm/curated', 'lab-curated.html'],
  ['/lab', 'lab.html'],
  ['/explore', 'explore.html'],
  ['/analytics', 'analytics.html'],
  ['/scores', 'scores.html'],
  ['/ticker', 'ticker.html'],
  ['/day', 'day.html'],
  ['/runs', 'runs.html'],
]

const routeTarget = (route) => {
  if (route === '' || route === '/') return 'overview.html'
  const hit = routes.find(([prefix]) => route === prefix || route.startsWith(`${prefix}/`))
  return hit ? hit[1] : null
}

const rewriteRoutes = (html, prefix) =>
  html.replace(/href="#([^"?]*)(?:\?[^"#]*)?"/g, (whole, route) => {
    const target = routeTarget(route)
    return target ? `href="${prefix}${target}"` : whole
  })

function documentFor(title, kind, body) {
  const routePrefix = kind === 'complete screen' ? '' : '../screens/'
  return `<!doctype html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="catalog-kind" content="${kind}">
<title>${title} · Signal Dashboard catalog</title>
<link rel="stylesheet" href="../assets/app.css">
<link rel="stylesheet" href="../assets/artifact.css">
</head>
<body>
<div class="catalog-ribbon"><a href="../index.html">← Catalog</a><span>${kind}</span><b>${title}</b></div>
${rewriteRoutes(body, routePrefix)}
</body>
</html>
`
}

for (const [slug, title] of screens) {
  writeFileSync(join(here, 'screens', `${slug}.html`), documentFor(title, 'complete screen', captured.get(slug)))
}
for (const [slug, title] of states) {
  writeFileSync(join(here, 'states', `${slug}.html`), documentFor(title, 'contextual state', captured.get(slug)))
}

// The index is generated too. Hand-maintaining it is how an inventory link and
// the files it points at drift apart.
const cards = (dir, list) => list.map(([slug, title, blurb]) =>
  `    <a class="catalog-card" href="${dir}/${slug}.html"><b>${title}</b><span>${blurb}</span></a>`).join('\n')

writeFileSync(join(here, 'index.html'), `<!doctype html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Signal Dashboard · Design catalog</title>
  <link rel="stylesheet" href="assets/app.css">
  <link rel="stylesheet" href="assets/artifact.css">
</head>
<body><main class="catalog">
  <div class="page-eyebrow">Static UI inventory</div>
  <h1>Signal Dashboard design catalog</h1>
  <p class="muted">Directly openable, full-context artifacts derived from the rendered dashboard snapshot.</p>
  <h2>Complete screens</h2>
  <div class="catalog-grid">
${cards('screens', screens)}
  </div>
  <h2>Contextual states</h2>
  <div class="catalog-grid">
${cards('states', states)}
  </div>
</main></body></html>
`)

console.log(`Wrote ${screens.length} screens, ${states.length} contextual states, the inventory, and shared CSS.`)
