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
- `composables/` — `useApi.js` is the authed fetch wrapper: injects the JWT, refreshes on 401 and retries once, redirects to login on failure. **Use `apiFetch` for all API calls**, don't call `fetch` directly.
- `@` alias → `src/` (configured in `vite.config.js`).
