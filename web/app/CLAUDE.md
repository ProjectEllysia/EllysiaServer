# CLAUDE.md — Web SPA

Vue 3 + Vite single-page app (Pinia + Vue Router). See the root [`../../CLAUDE.md`](../../CLAUDE.md) for backend/architecture context. Comments are in **Spanish** — match them.

## Commands (run from this directory)
```bash
npm install
npm run dev            # dev server on :80; proxies /oauth,/users,/system,/plans,/organizations,/themis,/aegis,/iris,/acheron,/hygeia → Flask :5000 (see vite.config.js)
npm run build

npm test               # all ten SPA suites; this is what CI runs
npm run test:acheron   # crypto interop + CRUD + sync for the Acheron vault client (node, in test/)
```

## Layout (`src/`)
- `views/` — one component per route, grouped like the API modules: `themis/`, `iris/`, `aegis/`, `hygeia/`, `acheron/`, `accounts/` (users, profile, plans, organization), `system/` (config, logs, queue, knowledge base) and `public/` (landing, login, legal pages, error — everything reachable without a session).
- `stores/` — Pinia stores, one per domain (`authStore`, `themisStore`, `mfaStore`, ...).
- `components/` — grouped by feature (`themis/`, `aegis/`, `iris/`, `acheron/`, `shared/`, ...). A module's plain-JS helpers and UI labels live next to its components (`components/<module>/<topic>.js`).
- `components/acheron/storableLabels.js` + `storableTypes.js` — the vault UI catalogue (i18n keys for each type and field plus form hints, composed with the schema). The crypto itself lives in `@projectellysia/acheron-core-web`; encryption is client-side and the server only ever sees ciphertext.
- `components/decor/` — the public pages' decoration, reusable by any view of a module: `ModuleAtmosphere` paints the module's mythological scene (`scenes/<Module>Scene.vue`; the sky ones are data for `StarChart`), `EmblemSeal` the guilloché seal around a hub's emblem (one pattern per module in `sealPatterns.js`), `ToolGlyph` the medallion of each free tool and `Frieze` the Greek-key band. The scenes are engraved from formulas and real data, not drawn by hand: keep the maths in the plain-JS modules beside them (`celestial.js`, `spectrum.js`, `cartography.js`, `sceneGeometry.js`), which `test/freeTools.motion.test.mjs` covers. Three budgets keep them light on an ordinary laptop: anything that moves forever moves a whole layer with `transform` (the sky drift, the seal, the frieze) or changes a few small elements with `steps()`, never animates a `filter` or a background position; anything that keeps moving *inside* an engraving (Iris's glint, Acheron's lantern and swell) lives in its own stacked `<svg class="layer layer--moving">` with the same `viewBox`, so its repaints never re-rasterise the plate (the test guards all three, and `stroke-dasharray: 1` for a draw-in lives only in the `draw` keyframes, so finished strokes are plain); and hairlines use `max(<width>px, calc(var(--device-pixel) * 1px))` so they never fall below one physical pixel (`composables/useDevicePixel.js`). `components/shared/moduleIdentity.js` is the registry of the six modules (numeral, name, epigraph, hub copy keys and capabilities) shared by hubs and tool pages; `assets/css/motion.css` and `directives/reveal.js` hold the shared entrance vocabulary, which must respect `prefers-reduced-motion`.
- `composables/` — `useApi.js` is the authed fetch wrapper: injects the JWT, refreshes on 401 and retries once, redirects to login on failure. **Use `apiFetch` for all API calls**, don't call `fetch` directly.
- `@` alias → `src/` (configured in `vite.config.js`).
