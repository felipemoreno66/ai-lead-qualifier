# ADR 0001: FastAPI owns the database, Next.js is a BFF

Status: accepted

## Context

The product has a public intake form, an operator dashboard and an agent that qualifies leads. Two runtimes
(Python for the agent, Next.js for the UI) could both touch Postgres, which would split the domain model and the
migrations across languages. The admin API must also never be reachable from a browser.

## Decision

FastAPI is the only writer to Postgres and holds all business logic; migrations are Alembic only
(SQLAlchemy 2 Core, async). Next.js never connects to the database. The dashboard talks to the agent through
Next.js route handlers (`/bff/*`), which validate input and responses with Zod and call `/admin/*` with a
server-side bearer token (`ADMIN_API_TOKEN`). The public intake endpoint `POST /api/leads/{slug}` lives in
FastAPI, with per-workspace CORS, so external sites and the hosted form use the same contract. State-changing BFF
requests need an anti-CSRF header and a same-origin check, and a per-request CSP nonce is set in `proxy.ts`.

## Consequences

- One domain model, one migration tool, and the admin token never reaches a browser.
- The browser needs no admin CORS; operator login can later be checked in one place (Next.js).
- Every dashboard action is two hops (browser, BFF, agent), and each BFF route needs its own Zod schemas
  (generated, see ADR 0010).
- Browsers reach only the public intake endpoint of the agent; the public demo (M4.3, in review) routes even
  that through the web server.

## Alternatives considered

- Next.js with its own database access: two writers and two schemas to keep in sync.
- Dashboard calling the admin API directly from the browser: exposes the token or needs a session model in
  the agent from day one.
