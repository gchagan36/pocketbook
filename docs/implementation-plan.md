# Pocketbook — Phased Implementation Plan

## Context

`budget-app-architecture.md` describes a self-hosted, single-user budget app but the repo is **greenfield**: only the design doc, a one-line README, and empty placeholder directories (`backend/{api,core,db,providers,sync,tests}`, `frontend/src/{api,components,pages}`, `docs/`, `scripts/`) plus a 0-byte `config/settings.py` exist. There is zero functional code.

This plan turns the architecture into an ordered backlog **you** implement. It is written PM→developer: each phase is a set of tasks with acceptance criteria, no skeleton code. Decisions locked in: **Python 3.12 + FastAPI backend, React + Vite + TS frontend**, provider order **CSV first → Plaid second** (the provider interface must still leave room for other aggregators later), full app through polish.

The golden rule threaded through every phase — **dependencies point one way**: `api`/`sync` → `core` + `db`; `providers` → `core` models only; `core` has no I/O; `db` → `core` models only. Keep all SQL inside `db/repositories`. If a task ever tempts you to import `db` from a provider or do I/O in `core`, stop — the layering is wrong.

---

## Phase 0 — Project setup & tooling

Goal: a runnable, linted, tested skeleton with dependency management in place before any feature code.

**Tasks**
1. Initialize `uv` in the repo root; create `pyproject.toml` targeting Python 3.12. Add runtime deps: `fastapi`, `uvicorn[standard]`, `pydantic`, `httpx`, `apscheduler`, `rapidfuzz`, `ofxparse`, `plaid-python`, and a crypto lib for the token vault (e.g. `cryptography`). Add dev deps: `pytest`, `ruff`.
2. Configure `ruff` (lint + format) in `pyproject.toml`; pick a line length and rule set and commit it so formatting never becomes a diff argument.
3. Configure `pytest` (test paths → `backend/tests`, import mode). Confirm `uv run pytest` collects zero tests successfully.
4. Turn `backend/` and its subpackages into real Python packages (add `__init__.py` where your import style needs them). Decide your import root now (e.g. `backend` as a top-level package) and stick to it.
5. Write `.env.example` documenting every variable the app will read: Plaid client ID + secret + environment (sandbox/development/production), token-vault encryption key, DB path override, API auth token/secret. Real `.env` stays gitignored.
6. Fill in `config/settings.py`: load non-secret behavior (active providers list, sync interval, DB path, categorization defaults) and read secrets from environment. Keep secrets and non-secrets conceptually separate per the doc. This module is the single source of config truth.
7. Add/verify `.gitignore` covers `.env`, `*.db`, `__pycache__`, `node_modules`, `frontend/dist`.

**Acceptance:** `uv run ruff check`, `uv run ruff format --check`, and `uv run pytest` all run clean on an empty test suite.

---

## Phase 1 — Data foundation (schema + models + repositories)

Goal: the canonical shapes everything speaks, plus the only layer allowed to touch SQL. Per the doc's build order, this comes first.

**Tasks**
1. **Canonical models (`core/models`)** — define Pydantic types: `Account`, `Transaction`, `Category`, `CategoryRule`, `Budget`, and a `SyncState` shape. Decide field-level details that dedup and budgets will depend on: money representation (store integer minor units / cents — do **not** use floats), a stable transaction fingerprint concept, pending vs posted status, provider-source tag, and category-confidence/needs-review flag. These types are shared across every layer; get them right before building on them.
2. **Schema DDL (`db/schema`)** — write SQLite DDL for accounts, transactions, categories, category_rules, budgets, and sync_state. Add the indexes dedup will need (account + amount + date range lookups) and a uniqueness strategy for transaction identity. Enable `PRAGMA foreign_keys` and choose date/text storage conventions.
3. **Migrations (`db/migrations`)** — establish a numbered, forward-only migration convention and make migration `0001` create the full schema. Write a tiny migration runner (tracks applied version in a table). This is infrastructure the `init-db` script and app startup both call.
4. **Repositories (`db/repositories`)** — write repository functions for each entity: account upsert/list, transaction upsert/query-by-filters/find-candidates-for-dedup, category + rule CRUD, budget CRUD, and sync-state get/advance-cursor. **All SQL lives here and nowhere else.** Repositories accept and return `core` models, not raw rows.
5. **`init-db` script (`scripts/`)** — creates the SQLite file and runs migrations to head. Idempotent.

**Acceptance:** running `init-db` produces a valid SQLite file; a repository round-trip test (insert an `Account` + `Transaction`, read them back as models) passes against a temp DB.

---

## Phase 2 — CSV provider + sync engine + dedup (fully offline)

Goal: the doc's most valuable early milestone — a complete ingest path testable with zero network and zero accounts. This is where dedup, the "hard problem isolated," gets built and hardened.

**Tasks**
1. **Provider contract (`providers/base`)** — define the interface every provider satisfies: *fetch accounts*, *fetch transactions since cursor*, *normalize raw payload → `core` models*. Design it so both a manual/file provider (CSV) and a push+cursor provider (Plaid, which additionally owns token exchange and webhook parsing) fit cleanly — the cursor abstraction should map to Plaid's `/transactions/sync` cursor. Providers import only `core` models — never `db`, `sync`, or `api`.
2. **CSV/OFX/QFX provider (`providers/csv_import`)** — parse uploaded files (`ofxparse` for OFX/QFX, stdlib `csv` for CSV) and normalize to canonical `Transaction`/`Account`. Handle the messy realities: header variations, date formats, sign conventions (debits vs credits), missing merchant fields. Normalization only — no DB writes.
3. **Fingerprinting + dedup (`sync/dedup`)** — implement transaction identity: exact-ID match when available, plus fuzzy fingerprint (same account, same amount, date within a small window, similar merchant string via `rapidfuzz`) for providers that re-send. Implement explicit **pending→posted reconciliation** (a pending txn re-arrives posted with a new ID → update, don't duplicate). This module gets the densest tests in the codebase.
4. **Sync engine (`sync/engine`)** — write once against the provider contract: fetch → normalize → dedup → upsert → advance cursor. Persist sync state (cursor, last-run time, error count) so restarts resume cleanly. The engine knows nothing about *which* provider it's running.
5. **Test fixtures (`tests/fixtures`)** — capture sanitized sample CSV/OFX payloads including edge cases (pending duplicates, same-day same-amount same-merchant, re-delivered history).
6. **Dedup + engine test suites** — cover pending→posted transitions, same-day duplicate amounts at one merchant, provider re-delivery of history. Add the end-to-end test: run the engine against a **fake in-memory provider** and assert on final DB state.

**Acceptance:** importing a fixture CSV twice yields no duplicates; a pending txn followed by its posted version resolves to one row; the fake-provider e2e test passes.

---

## Phase 3 — Core domain logic (categorization + budgets + reports)

Goal: pure, I/O-free business logic — fast to unit test, impossible to couple to a provider.

**Tasks**
1. **Categorization engine (`core/categorization`)** — run user-defined rules first (e.g. "merchant contains KROGER → Groceries"), fall back to provider-supplied category when present, and flag low-confidence matches for review. Use `rapidfuzz` for merchant matching. Pure functions over `core` models; persistence of rules and results happens in repositories, not here.
2. **Budget math (`core/budgets`)** — envelope arithmetic (spent vs allocated per category per period), rollover behavior, and month/period-boundary edge cases (variable month lengths, timezone-free date handling). Pure functions.
3. **Reports (`core/reports`)** — spending summaries, category breakdowns, and trends over time as pure computations over transaction lists.
4. **Wire categorization into sync** — the sync engine (or a post-upsert step) applies categorization to new transactions. Keep the decision logic in `core`; the orchestration/persistence in `sync`/`db`.
5. **Pure-function test suites** — categorization rule precedence and confidence flagging; budget rollover and month boundaries; report aggregation correctness.

**Acceptance:** categorization/budget/report tests pass with no DB or network involved; a newly synced transaction lands with a category (or a needs-review flag) applied.

---

## Phase 4 — API + minimal dashboard

Goal: expose the backend over HTTP and put a thin, functional UI in front of it. Per the doc, route handlers "read like a table of contents."

**Backend tasks (`api/`)**
1. **Middleware** — request auth (token/secret from env, worth having even single-user if network-accessible) and uniform JSON error handling.
2. **Routes** — thin handlers translating HTTP → `core`/`db` calls → JSON, no business logic:
   - accounts: list
   - transactions: list/filter, update category, mark reviewed
   - categories & rules: CRUD
   - budgets: CRUD + progress
   - sync-trigger: kick a manual sync of a given provider
   - file upload: accept a CSV/OFX for the `csv_import` provider
3. **App wiring** — FastAPI app that runs migrations on startup and (later) will serve the built React bundle as static files. Confirm the auto-generated OpenAPI docs render and act as your API explorer.

**Frontend tasks (`frontend/`)**
4. Scaffold React + Vite + TypeScript (`package.json`, `vite`, `tsconfig`). Add TanStack Query and Recharts.
5. **Typed API client (`frontend/src/api`)** — the single place that knows backend URLs and response shapes.
6. **Pages (`frontend/src/pages`)** — dashboard (summary), transactions (triage/recategorize uncategorized), budgets (progress), accounts, settings (incl. CSV upload). Map one-to-one to user actions. Leave a slot on the accounts/settings page for the Plaid Link widget added in Phase 5.
7. **Components (`frontend/src/components`)** — transaction table, category picker, budget bars, charts.

**Acceptance:** you can upload a CSV via the UI, watch transactions appear, recategorize one, set a budget, and see progress — all through the API, with OpenAPI docs available for manual exercise.

---

## Phase 5 — Plaid provider (Link + token vault + sync + webhooks)

Goal: automated, near-real-time ingest. Plaid is the heaviest provider — it adds a frontend Link flow, an encrypted token vault, a `/transactions/sync` client, and a webhook receiver — but it reuses the Phase 2 engine and dedup unchanged. Get an account and use the **sandbox** environment throughout development.

**Tasks**
1. **Token vault (`db` + crypto)** — store per-institution Plaid access tokens **encrypted at rest** in SQLite, with the encryption key supplied via `.env` (never in the DB). A leaked DB file alone must not expose live bank connections. Encrypt/decrypt helpers live near persistence; only the Plaid provider ever needs plaintext tokens. Add a repository + migration for the token store.
2. **Plaid provider (`providers/plaid`)** — using `plaid-python`:
   - *Link token exchange*: create a Link token, and exchange the short-lived public token returned by the frontend for a permanent access token → store encrypted in the vault.
   - *Sync*: call `/transactions/sync` with the stored per-item cursor, handling added/modified/removed batches and cursor pagination.
   - *Normalize*: map Plaid's payload (merchant name, category taxonomy, pending status) to canonical `core` models. Reuse the Phase 2 engine + dedup — no new orchestration.
3. **API routes for Plaid (`api/routes`)** — a create-link-token endpoint and a public-token-exchange endpoint for the Link flow, plus a **webhook receiver** that verifies/parses Plaid webhook payloads and triggers a sync for the affected item. Keep handlers thin; parsing lives in the provider.
4. **Scheduler (`sync/scheduler`)** — APScheduler in-process loop as a fallback/scheduled sync for Plaid items (webhooks are primary but polling covers missed events). Design the registration point so both the webhook-triggered path and the cron path funnel into the same engine call without touching `core`/`db`/`dedup`.
5. **Frontend Link widget** — embed Plaid Link on the accounts/settings page: call the create-link-token endpoint, run Link, post the resulting public token to the exchange endpoint. This is the only place the frontend touches a third party; the user's bank credentials never reach your app.
6. **Fixtures + tests** — sanitized `/transactions/sync` payloads (including added/modified/removed and pending→posted cases); normalization tests; confirm the same-payload-twice = no-duplicates guarantee holds through the Plaid path. Test token encrypt/decrypt round-trip.
7. **Settings + provider selection** — make `config/settings.py`'s active-providers list drive which providers the scheduler and sync-trigger route run (CSV and Plaid coexisting).

**Acceptance:** in Plaid sandbox you can link an institution via Link, tokens are stored encrypted (verify the raw DB shows no plaintext token), a `/transactions/sync` run dedups transactions into the DB, and a simulated webhook triggers a sync; fixture tests pass offline.

---

## Phase 6 — Polish

Goal: the quality-of-life layer and deployment.

**Tasks**
1. **Reports UI** — surface `core/reports` as spending trends, category breakdowns, and budget-vs-actual charts (Recharts) on the dashboard.
2. **Historical backfill script (`scripts/`)** — bulk-import a date range / large file set through the CSV provider and engine, safe to re-run (dedup protects it).
3. **Data export script (`scripts/`)** — dump transactions/budgets to CSV/JSON for portability and backup.
4. **Single-process deployment** — FastAPI serves the built React `dist/` as static files; APScheduler runs in the same process; document the run command and the backup story (copy the one `.db` file + keep the env key). Add a short deploy section to `docs/`.
5. **Provider setup guides (`docs/`)** — how to create a Plaid developer account, get client ID/secret, move from sandbox → development/production, and configure `.env` (incl. the token-vault key). Document the webhook URL setup.
6. **Alternate-provider readiness note** — document (don't build) that adding another aggregator later (e.g. SimpleFIN — a single authenticated GET + normalization) touches only `providers/<name>/` plus one scheduler registration, confirming the abstraction held. Note that Plaid access tokens are the sensitive asset and the vault design already isolates them.

**Acceptance:** one `uv run` command serves API + UI + scheduler together; backup = copy one file; backfill and export scripts work end-to-end.

---

## Cross-cutting verification

- **Per phase:** `uv run ruff check`, `uv run ruff format --check`, `uv run pytest` stay green before moving on.
- **Layering guard:** periodically confirm no `providers/*` file imports `db`/`sync`/`api`, and no `core/*` file performs I/O. This is the invariant that keeps the provider swap free — consider a simple import-linter rule or a grep check in CI.
- **Dedup is the canary:** the "same fixture imported twice = zero duplicates" test should exist and pass from Phase 2 onward, and again through the Plaid `/transactions/sync` path in Phase 5.
- **Secrets at rest:** after Phase 5, inspect the raw SQLite file and confirm no Plaid access token appears in plaintext; the vault key lives only in the environment.
- **End-to-end smoke:** fake-in-memory-provider → engine → DB state assertion (Phase 2) is your fastest full-loop regression test; keep it green.

## Files/dirs that already exist to build into
- `config/settings.py` (empty stub → fill in Phase 0)
- `backend/{api,core,db,providers,sync,tests}/` (empty → populate per phase)
- `frontend/src/{api,components,pages}/` (empty → populate Phase 4)
- `docs/`, `scripts/` (empty → populate Phases 1/6)
