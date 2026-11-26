# Deploying the public demo (Tailscale Funnel)

Runs the Northwind demo on your own machine and publishes **only the web app** at
`https://<machine>.<tailnet>.ts.net` with [Tailscale Funnel](https://tailscale.com/kb/1311/tailscale-funnel).
No hosting account, no cost. Visitors get an open dashboard with fictional data; there is no login.

What the public demo guarantees (enforced in `docker-compose.public.yml` and in the agent settings, which
refuse to start otherwise):

- Fake LLM provider only, no API key in the containers, orchestration inline (no n8n).
- Emails only to the internal Mailpit (UI on `127.0.0.1:18025`, never published).
- Only the web port is published, on `127.0.0.1`. Agent API, Postgres and n8n publish nothing.
- Secrets are generated at setup; the `local-dev-*` defaults are rejected.
- Strict headers (CSP, HSTS, COOP/CORP), per-visitor and global rate limits, lead deletion disabled,
  visible "Public demo" banner, nightly reset.

## Requirements

- Docker with Compose 2.24+ and Tailscale on the server.
- Resources: about **1.1 GB of RAM** (agent with embedding model, Postgres, web, Mailpit, reset service) on
  the 8 GB server. Stop other stacks that use ports 3000 or 18025 (or set `DEMO_WEB_PORT` / `DEMO_MAILPIT_PORT`).
- **The demo is only reachable while the server is on and Docker and Tailscale are running.**

## One-time Tailscale setup

1. In the Tailscale admin console enable **MagicDNS** and **HTTPS certificates** (DNS page).
2. Allow Funnel for this machine: in the access controls (Access controls page) the node needs the `funnel`
   attribute, e.g. `"nodeAttrs": [{"target": ["autogroup:member"], "attr": ["funnel"]}]`. The first
   `tailscale funnel` run prints a link that offers to enable it.
3. To run `tailscale` without `sudo`, once: `sudo tailscale set --operator=$USER`.

## Start

```bash
cd ai-lead-qualifier
scripts/public-demo.sh init      # creates .env.public (gitignored) with generated secrets and PUBLIC_URL
scripts/public-demo.sh up        # builds and starts the stack; first start downloads a ~90 MB model
```

`up` runs `docker compose -p alq-demo --env-file .env.public -f docker-compose.yml -f docker-compose.public.yml up -d --build`.
If `init` could not detect your name, edit `PUBLIC_URL` in `.env.public` (must be the exact public URL: the
agent uses it as the allowed web origin). Check it works locally: <http://127.0.0.1:3000>.

Publish it (this puts the demo on the internet):

```bash
tailscale funnel --bg 3000
tailscale funnel status          # prints the public URL
```

`--bg` keeps Funnel on across reboots. The public URL is `https://<machine>.<tailnet>.ts.net`; open it from a
phone on mobile data to confirm it is really public, then put it in the README ("Live demo").

## Operate

| Task | Command |
|---|---|
| Status (containers + Funnel) | `scripts/public-demo.sh status` |
| Reset to the seeded data now | `scripts/public-demo.sh reset` |
| Logs | `scripts/public-demo.sh logs [service]` |
| Emails the demo "sent" | open `http://127.0.0.1:18025` on the server |
| Stop, keep data | `scripts/public-demo.sh down` |
| Stop and delete data | `scripts/public-demo.sh destroy` |

The `demo-reset` service resets every night at `DEMO_RESET_AT` (default `04:00` UTC; or every
`DEMO_RESET_INTERVAL_HOURS`): it deletes everything visitors created (leads, drafts, questions, rate-limit
counters, stored mail) and reloads the fictional data. It logs each run (`scripts/public-demo.sh logs demo-reset`)
and is safe to run twice.

## Stop publishing

```bash
tailscale funnel --https=443 off     # unpublish (or: tailscale funnel reset)
scripts/public-demo.sh down
```

## Notes and checks

- Funnel appends the visitor address to `X-Forwarded-For`; the web server keys its limits on the last entry.
  Without the header all callers would share one limit, which still protects but is coarse: check that
  `scripts/public-demo.sh logs web` shows no 429s for a single normal visit.
- If review, ask or form actions answer 403 "Cross-origin", the Host seen by the web server differs from the
  browser's; `TRUST_FORWARDED_HOST=true` is already set in the override.
- Funnel runs on the host, outside Docker's firewall bypass: nothing else is exposed, but never change the
  override to publish the agent or Postgres ports.
- Real use of this project (a private instance with login and real data) is a different deployment; do not
  load real leads into the demo.
