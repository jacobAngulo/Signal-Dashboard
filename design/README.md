# Design catalog

Open [`catalog/index.html`](catalog/index.html) to browse the maintained UI inventory. Each artifact is a complete, directly openable HTML document with the full app context around the screen or interaction state.

## Inventory

Complete screens: Overview, Explore, Analytics, Lab, Lab · curated, Scores, Ticker, Day, and Runs.

Contextual states: populated global ticker search, signal-detail drawer, docked signal inspector, feedback panel, Lab · filtered, and Lab · undefined producer. Small components such as cards, buttons, filters, and tables stay inside their parent artifact rather than getting their own files.

Everything above is recorded from the running app -- states included. See [`AGENTS.md`](AGENTS.md).

Shared app styling is copied from `frontend/src/styles.css` to `catalog/assets/app.css`; catalog-only framing lives at `catalog/assets/artifact.css`. `dashboard-snapshot.html` remains the monolithic DOM provenance source.

## Updating

After regenerating the monolithic snapshot, run:

```sh
node design/catalog/build.mjs
node design/catalog/validate.mjs
```

`build.mjs` regenerates `screens/`, `states/`, `index.html` and `assets/app.css`; the two directories are emptied first, so nothing survives that the inventory no longer lists. Frontend changes must follow the maintenance contract in [`AGENTS.md`](AGENTS.md).

## Monolithic snapshot provenance

`dashboard-snapshot.html` is the whole dashboard as one static file: every
route's real rendered DOM, with `frontend/src/styles.css` inlined verbatim.
It is what to hand Claude Design, instead of the repo.

## Why not just send the frontend folder

`frontend/` is ~15 MB of recorded fixtures plus `node_modules` plus a Vite
build step, and the markup a designer needs to see does not exist in any file
there — it is produced at runtime by React from fixture JSON. The snapshot is
that output, frozen: no build, no data layer, no framework, ~1 MB, opens in
a browser.

## Regenerating

The fixture dev server has to be up, because the snapshot is a recording of
what the app actually renders:

```
cd frontend
npm run dev:fixtures     # in one shell, serves on :5173
npm run design:snapshot  # in another
```

`scripts/snapshot.mjs` drives a headless browser over the nine routes, then
over the six interaction states, and copies `#root`'s inner HTML each time;
`scripts/shrink.py` rounds SVG geometry and collapses whitespace between tags.
Neither touches the stylesheet's colours or any rendered number — the shrink
pass is scoped to SVG geometry attributes for exactly that reason.

`SNAPSHOT_BASE` overrides the dev-server origin. It exists because the Lab
calls `/api/lab`, which has no recorded fixture yet: until
`scripts/capture_api_fixtures.py` is run on a box with the producer data,
`npm run dev:fixtures` alone cannot render the two Lab screens or the two Lab
states, and the capture has to be pointed at something that answers that
endpoint. Everything else works off the committed fixtures.

Three deliberate lossy steps, all noted in the file itself:

- table bodies are trimmed to 8 rows, with a row saying how many were dropped
- the route slugs and their arguments are hardcoded at the top of
  `snapshot.mjs`; the ticker and dates there must exist in the fixture slice
  or the section captures an error box instead of a screen
- a state is whatever the scripted interaction produced on that run, so the
  selected row or the constrained facet can differ between recordings

## Bringing a redesign back

Class names are the contract in both directions. The stylesheet carries 146 of
them and the JSX only ever names them as strings, so a restyle that keeps the
class names is a `styles.css` diff and nothing else. That is how theme 2a
landed: no component file changed for the colours.

Anything that needs *new* markup — a different table shape, a card that splits
in two — is a JSX change, and the snapshot cannot express it. Say so in the
prompt rather than letting a new class name arrive with no element to attach
to.

Colours live in one place: the `:root` token block at the top of
`styles.css`. JS reads them back through `frontend/src/theme.js` for the SVG
charts, so a hue changed in CSS reaches recharts without a second edit. Do not
reintroduce colour literals in the JSX.
