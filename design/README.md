# design/

`dashboard-snapshot.html` is the whole dashboard as one static file: every
route's real rendered DOM, with `frontend/src/styles.css` inlined verbatim.
It is what to hand Claude Design, instead of the repo.

## Why not just send the frontend folder

`frontend/` is ~15 MB of recorded fixtures plus `node_modules` plus a Vite
build step, and the markup a designer needs to see does not exist in any file
there — it is produced at runtime by React from fixture JSON. The snapshot is
that output, frozen: no build, no data layer, no framework, ~630 KB, opens in
a browser.

## Regenerating

The fixture dev server has to be up, because the snapshot is a recording of
what the app actually renders:

```
cd frontend
npm run dev:fixtures     # in one shell, serves on :5173
npm run design:snapshot  # in another
```

`scripts/snapshot.mjs` drives a headless browser over the eight routes and
copies `#root`'s inner HTML; `scripts/shrink.py` rounds SVG geometry and
collapses whitespace between tags. Neither touches the stylesheet's colours or
any rendered number — the shrink pass is scoped to SVG geometry attributes for
exactly that reason.

Two deliberate lossy steps, both noted in the file itself:

- table bodies are trimmed to 8 rows, with a row saying how many were dropped
- the route slugs and their arguments are hardcoded at the top of
  `snapshot.mjs`; the ticker and dates there must exist in the fixture slice
  or the section captures an error box instead of a screen

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
