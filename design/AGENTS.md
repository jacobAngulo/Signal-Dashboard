# Design artifact maintenance

These instructions apply to `design/` and are part of the frontend definition of done.

When a frontend change affects layout, navigation, visible content, interaction states, or shared styling, update every affected artifact in `design/catalog/` in the same change. The catalog is not optional documentation and must not knowingly drift from the application.

## Granularity

- Add one file under `catalog/screens/` for each complete application screen or route-level composition.
- Add one file under `catalog/states/` for an independently meaningful state that changes the holistic composition, such as a modal, drawer, docked inspector, populated search result, or substantial empty/error state.
- Do not add separate files for ordinary cards, buttons, tables, filter values, tabs, or other small components. Keep those visible in their parent screen or state.
- Every artifact must retain the full surrounding application context. Never crop an overlay or component out into an isolated specimen.

## Everything is captured, nothing is hand-written

Screens *and* states are recorded from the running app by `frontend/scripts/snapshot.mjs`: a screen is a route, a state is a route plus a scripted interaction (type in the search box, click a row, open the feedback panel, constrain two lab facets). Artifacts are never produced by rewriting another artifact's markup -- a regex over HTML drifts silently the moment a component changes, whereas a click that finds no element fails the capture.

So: to add a state, add an entry to `STATES` in `snapshot.mjs` with the interaction that produces it. To retire one, delete that entry.

## Required update checklist

1. Regenerate `dashboard-snapshot.html` when the rendered DOM or data examples changed (see `README.md` -- the fixture dev server has to be up, and the lab needs something answering `/api/lab`).
2. Run `node design/catalog/build.mjs`. It rewrites `screens/`, `states/`, `index.html`, and `assets/app.css` from the snapshot and from `frontend/src/styles.css`; the directories are emptied first, so a retired artifact leaves no orphan.
3. If an artifact was added, removed, or renamed, update the `screens`/`states` lists in `build.mjs`, its markers in `validate.mjs`, and the human inventory in `design/README.md`. The catalog index is generated -- do not hand-edit `catalog/index.html`.
4. Keep the route map in `build.mjs` synchronized with `frontend/src/nav.js` and the header nav. Shared visual rules belong in `catalog/assets/app.css` (generated) or `artifact.css` (catalog-only chrome), not copied into individual pages.
5. Open representative screen and state files directly, then run `node design/catalog/validate.mjs` and the normal frontend build/tests appropriate to the UI change.

`validate.mjs` checks more than link integrity: each artifact must still contain the element that makes it what it claims to be (`.drawer-overlay`, `.rail-active` with a touched facet, the lab's `.facet` rail), must carry full app context, and must contain no unrewritten `#/` route.

The original monolithic snapshot remains provenance and the regeneration source. Do not delete it as part of ordinary catalog maintenance.
