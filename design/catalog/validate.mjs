import { existsSync, readFileSync, readdirSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = dirname(fileURLToPath(import.meta.url))
const expected = {
  screens: ['overview', 'explore', 'analytics', 'lab', 'lab-curated', 'scores', 'ticker', 'day', 'runs'],
  states: ['ticker-search-populated', 'signal-detail-drawer', 'signal-inspector', 'feedback-panel',
           'lab-filtered', 'lab-undefined-producer'],
}
const artifactFiles = Object.entries(expected).flatMap(([dir, slugs]) =>
  slugs.map((slug) => `${dir}/${slug}.html`)
)
const files = ['index.html', ...artifactFiles]
const errors = []

for (const [dir, slugs] of Object.entries(expected)) {
  const actual = readdirSync(join(root, dir)).filter((name) => name.endsWith('.html')).sort()
  const wanted = slugs.map((slug) => `${slug}.html`).sort()
  if (actual.join('\n') !== wanted.join('\n')) {
    errors.push(`${dir}: expected exactly ${wanted.join(', ')}; found ${actual.join(', ')}`)
  }
}

for (const file of files) {
  const absolute = join(root, file)
  const html = readFileSync(absolute, 'utf8')
  if (!/^<!doctype html>/i.test(html)) errors.push(`${file}: missing doctype`)
  if (!/<html lang="en">/.test(html) || !/<title>[^<]+<\/title>/.test(html)) errors.push(`${file}: missing document metadata`)
  for (const match of html.matchAll(/(?:href|src)="([^"]+)"/g)) {
    const target = match[1]
    if (/^(?:https?:|data:|mailto:|#)/.test(target)) continue
    const path = resolve(dirname(absolute), target.split('#')[0].split('?')[0])
    if (!existsSync(path)) errors.push(`${file}: broken local reference ${target}`)
  }
}

const index = readFileSync(join(root, 'index.html'), 'utf8')
for (const file of artifactFiles) {
  if (!index.includes(`href="${file}"`)) errors.push(`index.html: missing inventory link to ${file}`)
}

// What makes each artifact the thing it claims to be. A state whose defining
// element stopped rendering is a stale artifact, not a passing build.
const markers = {
  'screens/overview.html': ['class="hm"'],
  'screens/lab.html': ['class="lab-rail"', 'class="facet"', 'class="vcard'],
  'screens/lab-curated.html': ['class="candidate-table"', 'class="seg-btn is-on"'],
  'screens/analytics.html': ['class="meter-track"'],
  'screens/ticker.html': ['class="chart-legend'],
  'screens/runs.html': ['class="hm"'],
  'states/signal-detail-drawer.html': ['class="drawer-overlay"'],
  'states/signal-inspector.html': ['class="inspector"'],
  'states/ticker-search-populated.html': ['class="search-drop"'],
  'states/feedback-panel.html': ['class="feedback-panel"'],
  'states/lab-filtered.html': ['class="rail-active"', 'chip chip-active', 'facet is-touched'],
  'states/lab-undefined-producer.html': ['no row set defined'],
}
for (const file of artifactFiles) {
  const html = readFileSync(join(root, file), 'utf8')
  for (const marker of ['class="catalog-ribbon"', 'class="app"', '<header>', '<main id="main-content"']) {
    if (!html.includes(marker)) errors.push(`${file}: missing full-context marker ${marker}`)
  }
  for (const stylesheet of ['../assets/app.css', '../assets/artifact.css']) {
    if (!html.includes(`href="${stylesheet}"`)) errors.push(`${file}: missing shared stylesheet ${stylesheet}`)
  }
  for (const marker of markers[file] || []) {
    if (!html.includes(marker)) errors.push(`${file}: missing defining marker ${marker}`)
  }
  // A catalog page is static: a live hash route in it is a dead link.
  for (const match of html.matchAll(/href="#\/([^"]*)"/g)) {
    errors.push(`${file}: unrewritten application route #/${match[1]}`)
  }
}

if (errors.length) {
  console.error([...new Set(errors)].slice(0, 40).join('\n'))
  process.exit(1)
}
console.log(`Validated ${files.length} HTML files (${expected.screens.length} screens, ${expected.states.length} states); inventory, context, state markers, styles, and local links are intact.`)
