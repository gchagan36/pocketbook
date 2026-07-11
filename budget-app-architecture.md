# Personal Budget App — Architecture & Codebase Structure

A self-hosted budget application that automatically pulls transactions from bank and credit card accounts, categorizes spending, and tracks budgets. This document covers the system architecture (two variants: Plaid and SimpleFIN Bridge) and the codebase structure that supports either — or both.

---

## Part 1: Application Architecture

### Shared foundation

Both variants share the same core system:

- **Backend service** — a small server (Python or Node) that owns all business logic: syncing transactions, deduplication, categorization, and budget math.
- **SQLite database** — single-file storage for accounts, transactions, categories, budgets, and sync state. Ideal for a single-user, self-hosted app; trivially easy to back up.
- **Web UI** — a dashboard for reviewing transactions, managing categories and rules, and tracking budget progress. Talks only to your backend, never to third parties.

The variants differ only in the **data acquisition layer** — how transactions get from your financial institutions into your backend.

### Variant A: Plaid

**Flow:** Your banks and cards → Plaid API → Your backend → SQLite ⇄ Web UI

1. **Account linking.** The web UI embeds Plaid's Link widget. You authenticate with your bank inside Plaid's flow — your credentials never touch your own app. Link returns a short-lived public token.
2. **Token exchange.** The backend exchanges the public token for a permanent access token per institution and stores it encrypted (the "token vault").
3. **Syncing.** The backend calls Plaid's `/transactions/sync` endpoint, which returns added/modified/removed transactions relative to a cursor. Sync can run on a schedule, or be triggered by Plaid webhooks that fire when new data is available.
4. **Processing.** New transactions are normalized, deduplicated against existing records, categorized, and upserted into SQLite.

**Properties:**
- Broadest institution coverage of any aggregator
- Near-real-time freshness via webhooks
- Rich metadata (merchant names, Plaid's own category taxonomy, pending status)
- More moving parts: Link widget in the frontend, token exchange, webhook endpoint, developer account setup
- Free tier suitable for personal use (limited number of linked items)

### Variant B: SimpleFIN Bridge

**Flow:** Your banks and cards → SimpleFIN Bridge → Your backend → SQLite ⇄ Web UI

1. **Account linking.** Done once on SimpleFIN Bridge's website — not in your app. Bridge maintains the bank connections (via MX under the hood) and issues you a single **access URL**.
2. **Syncing.** The backend makes an authenticated HTTPS GET to the access URL on a schedule (e.g., every few hours) and receives all accounts and transactions as JSON. No SDK, no OAuth, no webhooks.
3. **Processing.** Identical to Variant A: normalize, dedup, categorize, upsert.

**Properties:**
- Dramatically simpler integration — the entire sync client is a small polling function
- Read-only by design: the access URL can expose data if leaked, but can never move money
- Frontend is purely a dashboard; account linking never touches your app
- Narrower institution coverage than Plaid; data freshness limited by your polling interval
- Sparse metadata — you own categorization entirely
- Small annual fee

### Variant C (fallback): Manual file import

Nearly every bank exports CSV/OFX/QFX. A file importer provides a zero-dependency, fully private fallback — useful when an aggregator connection breaks, or as the primary path if you prefer never granting third-party access. In this codebase it is implemented as just another provider (see Part 2), so it coexists with either variant.

### Choosing (or not choosing)

Everything downstream of data acquisition — schema, dedup, categorization, budgets, UI — is identical across variants. The codebase structure below abstracts the acquisition layer behind a provider interface, so the practical recommendation is: **build against SimpleFIN or CSV first (simplest), and add Plaid later if you want broader coverage or webhook freshness.** No rewrite required.

---

## Part 2: Codebase Structure

### Directory layout

```
budget-app/
├── README.md
├── .env.example              # documented env vars, never real secrets
├── config/
│   └── settings              # app config: active provider(s), sync interval, db path
│
├── backend/
│   ├── api/                  # HTTP layer (thin — no business logic)
│   │   ├── routes/           # accounts, transactions, budgets, sync-trigger
│   │   └── middleware/       # auth (even single-user), error handling
│   │
│   ├── providers/            # ★ bank-data integration layer
│   │   ├── base              # the provider interface contract
│   │   ├── plaid/            # Link token exchange, webhook handling, /transactions/sync client
│   │   ├── simplefin/        # access-URL polling, JSON normalization
│   │   └── csv_import/       # manual OFX/CSV/QFX fallback
│   │
│   ├── sync/                 # orchestration
│   │   ├── engine            # runs a sync: fetch → normalize → dedup → upsert
│   │   ├── scheduler         # cron loop and/or webhook receiver
│   │   └── dedup             # pending→posted matching, transaction fingerprinting
│   │
│   ├── core/                 # domain logic (pure — no I/O, no framework imports)
│   │   ├── models            # canonical Transaction, Account, Budget, Category
│   │   ├── categorization    # rules engine + merchant matching
│   │   ├── budgets           # envelope math, rollover logic, period boundaries
│   │   └── reports           # spending summaries, trends, category breakdowns
│   │
│   ├── db/                   # persistence
│   │   ├── schema            # SQLite DDL
│   │   ├── migrations        # numbered, forward-only migration files
│   │   └── repositories      # ALL SQL lives here — nowhere else in the codebase
│   │
│   └── tests/                # mirrors backend structure; fixtures/ holds fake provider payloads
│
├── frontend/
│   └── src/
│       ├── pages/            # dashboard, transactions, budgets, accounts, settings
│       ├── components/       # charts, transaction table, category picker, budget bars
│       └── api/              # typed client wrapping the backend routes
│
├── scripts/                  # one-off utilities: init-db, historical backfill, data export
└── docs/                     # this document, provider setup guides, schema notes
```

### Layer responsibilities

**`api/` — HTTP layer.** Routes translate HTTP requests into calls on `core` and `db`, and translate results back into JSON. No business logic lives here; a route handler should read like a table of contents. Middleware handles authentication (worth having even for a single-user app if it's network-accessible) and uniform error responses.

**`providers/` — data acquisition.** Each provider implements the same contract defined in `base`:

- *fetch accounts* — return the institutions/accounts this provider can see
- *fetch transactions since cursor* — return new/changed transactions relative to a sync position
- *normalize* — convert the provider's raw payload into the canonical `Transaction` and `Account` models from `core`

Providers know nothing about the database, the scheduler, or each other. The Plaid provider additionally owns Link token exchange and webhook payload parsing; the SimpleFIN provider is little more than an authenticated GET plus normalization; the CSV provider parses uploaded files. Because all three satisfy the same contract, they can run side by side (e.g., Plaid for your bank, CSV for a credit union Plaid doesn't support).

**`sync/` — orchestration.** The engine is written once, against the provider contract: given a provider, fetch → normalize → dedup → upsert, then advance the cursor. The scheduler decides *when* the engine runs — a cron loop for polling providers (SimpleFIN), a webhook receiver for push providers (Plaid), or a manual trigger from the UI. Sync state (cursors, last-run timestamps, error counts) is persisted so restarts resume cleanly.

**`sync/dedup` — the hard problem, isolated.** Banks re-send pending transactions with different IDs when they post, and some providers occasionally re-deliver history. Naive ID matching produces duplicates; the dedup module owns fingerprint matching instead — same account, same amount, date within a small window, similar merchant string — plus explicit pending→posted reconciliation. Keeping this in one module with heavy test coverage pays for itself many times over.

**`core/` — pure domain logic.** Models define the canonical shapes everything else speaks. Categorization runs user-defined rules first (e.g., "merchant contains KROGER → Groceries"), falling back to provider-supplied categories when available, and flags low-confidence matches for review. Budgets own envelope arithmetic, rollover behavior, and month-boundary edge cases. Nothing in `core` performs I/O, which makes it fast to unit-test and impossible to couple to any provider or framework.

**`db/` — persistence.** The schema covers accounts, transactions, categories, category rules, budgets, and sync state. Migrations are numbered and forward-only. Repositories are the only files in the codebase containing SQL; everything else calls repository functions. When the schema changes, exactly one layer changes with it.

**`frontend/` — dashboard.** Pages map one-to-one to what a user does: review the dashboard, triage uncategorized transactions, adjust budgets, manage accounts. The API client module is the single place that knows backend URLs and response shapes. In the Plaid variant, the accounts/settings page additionally hosts the Link widget; in the SimpleFIN variant the frontend has no third-party integration at all.

### Dependency rules

Dependencies point in one direction only:

```
api ──────┐
          ├──▶ core ◀── providers
sync ─────┤
          └──▶ db  (repositories)
```

- `api` and `sync` may call `core` and `db`
- `providers` depend only on `core` models (for normalization targets) — never on `db`, `sync`, or `api`
- `core` depends on nothing internal and performs no I/O
- `db` depends only on `core` models
- `frontend` talks to `api` over HTTP and knows nothing else

These rules are what make the provider swap free: adding or removing Plaid touches `providers/plaid/`, one scheduler registration, and (for Plaid specifically) one webhook route and one frontend page — nothing in `core`, `db`, or dedup.

### Configuration & secrets

- `.env` holds secrets: Plaid client ID/secret, the SimpleFIN access URL, the token-vault encryption key. `.env.example` documents every variable with placeholder values and ships in the repo; `.env` never does.
- `config/settings` holds non-secret behavior: which providers are active, polling interval, database path, categorization defaults.
- Plaid access tokens are stored encrypted at rest in SQLite, with the encryption key supplied via environment — a leaked database file alone should not expose live bank connections.

### Testing strategy

- `tests/fixtures/` contains captured (sanitized) example payloads from each provider, so provider normalization and the sync engine are tested without network access.
- Dedup gets the densest test suite: pending→posted transitions, same-day duplicate amounts at the same merchant, provider re-delivery of history.
- `core` logic (categorization rules, budget math, month boundaries) is pure-function tested.
- A small end-to-end test runs the sync engine against a fake in-memory provider and asserts on database state.

### Suggested build order

1. Schema + repositories + canonical models
2. CSV provider + sync engine + dedup (fully testable offline, no accounts needed)
3. Categorization rules and budget math in `core`
4. API routes and a minimal dashboard
5. SimpleFIN provider (small) or Plaid provider (Link flow, token vault, webhooks)
6. Polish: reports, backfill script, export
