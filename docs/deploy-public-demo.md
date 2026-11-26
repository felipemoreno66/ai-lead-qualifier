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

- Docker with Compose 2.24+ and **Tailscale 1.52 or newer** on the server (`tailscale version`; `--bg` needs 1.52+).
- Resources: about **1.1 GB of RAM** (agent with embedding model, Postgres, web, Mailpit, reset service) on
  the 8 GB server. Stop other stacks that use ports 3000 or 18025 (or set `DEMO_WEB_PORT` / `DEMO_MAILPIT_PORT`).
- **The demo is only reachable while the server is on and Docker and Tailscale are running.**

## One-time Tailscale setup

1. In the Tailscale admin console enable **MagicDNS** and **HTTPS certificates** (DNS page).
2. Allow Funnel for this machine: in the access controls (Access controls page) the node needs the `funnel`
   attribute, e.g. `"nodeAttrs": [{"target": ["autogroup:member"], "attr": ["funnel"]}]`. The first
   `tailscale funnel` run prints a link that offers to enable it.
3. To run `tailscale` without `sudo`, once: `sudo tailscale set --operator=$USER`.
4. Funnel can only listen on ports **443, 8443 and 10000**. The commands below use 443.

## Start

```bash
cd ai-lead-qualifier
scripts/public-demo.sh init      # creates .env.public (gitignored) with generated secrets and PUBLIC_URL
scripts/public-demo.sh up        # builds and starts the stack; first start downloads a ~90 MB model
```

`up` runs `docker compose -p alq-demo --env-file .env.public -f docker-compose.yml -f docker-compose.public.yml up -d --build`.
If `init` could not detect your name, edit `PUBLIC_URL` in `.env.public` (must be the exact public URL: the
agent uses it as the allowed web origin). Check it works locally: <http://127.0.0.1:3000>.

If port 3000 is already used on the server, set `DEMO_WEB_PORT` (for example `3100`) in `.env.public` and use
that number in the Funnel command.

Before publishing, look at what Tailscale already serves on this machine: **`tailscale funnel` replaces any
existing `serve`/`funnel` configuration on port 443.**

```bash
tailscale serve status           # empty output means nothing would be replaced
```

Publish it (this puts the demo on the internet):

```bash
tailscale funnel --bg 3000
tailscale funnel status          # prints the public URL
```

The first time, the HTTPS certificate and the DNS record for the name can take a few minutes to appear; until
then the URL fails to load. `--bg` keeps Funnel on across reboots. The public URL is `https://<machine>.<tailnet>.ts.net`; open it from a
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

## Verify the visitor IP (do this once)

The rate limits are per visitor, so they need the real client address. Funnel runs on the host and is
expected to append the caller's address to `X-Forwarded-For`; the web server keys on the **last** entry.
This is not documented by Tailscale, so verify it. From **another network** (a phone on mobile data, not the
tailnet or the server):

```bash
# on the server, in a second terminal
scripts/public-demo.sh logs web | grep demo_client_key

# from the other network
curl -s -o /dev/null -H 'X-Forwarded-For: 1.2.3.4' https://<machine>.<tailnet>.ts.net/bff/workspaces
```

The web log line shows a hashed key (never the address) and the number of `X-Forwarded-For` entries:

- `"forwarded_entries":2` and the key is the same for repeated calls from your phone but different from a call
  from another network: **working** (your fake `1.2.3.4` plus the address Funnel appended).
- `"forwarded_entries":1`: Funnel did not add its own entry; your fake header is being trusted, so a visitor
  could dodge the per-visitor limit by changing it.
- `"forwarded_entries":0`: Funnel sends no header; every visitor shares one key.

In the last two cases the per-visitor limits are weak or coarse, but the **global caps per hour** still bound
total traffic (intake 100, Ask 150, review 600, reads 6000), so the demo cannot be flooded into a large bill or
outage; it can only be used up for a while. If you see that, tell the maintainer rather than raising limits.
The agent also logs `client_resolved` at debug level (`LOG_LEVEL=DEBUG` in `.env.public`, then `up` again) with
the hashed key it used for intake.

## Troubleshooting

| Symptom | Check |
|---|---|
| The public URL does not load | `tailscale status` (is the node connected?), `tailscale funnel status` (is it listed with "Funnel on"?). Wait a few minutes after the first run for the certificate. |
| "Funnel not enabled" message | Enable it with the link the command prints, or add the `funnel` attribute (see above). |
| Local URL works, public does not | `curl -I http://127.0.0.1:3000` on the server; then `tailscale funnel status` must point at that same port. |
| Port 3000 or 18025 already in use | Set `DEMO_WEB_PORT` / `DEMO_MAILPIT_PORT` in `.env.public`, run `up` again and redo the Funnel command with the new port. |
| Everything answers 429 | Reads, Ask, review and the form have per-visitor and global hourly caps; they reset on their own. |

## The nightly reset

At 04:00 UTC (`DEMO_RESET_AT`) the demo is rebuilt. The leads list is **empty for a few seconds to a minute**
while the data is reloaded (longer if the embedding model has to be loaded); visitors in that moment see an
empty dashboard or an error and just need to reload.

## Notes

- If review, ask or form actions answer 403 "Cross-origin", the Host seen by the web server differs from the
  browser's; `TRUST_FORWARDED_HOST=true` is already set in the override.
- Funnel runs on the host, outside Docker's firewall bypass: nothing else is exposed, but never change the
  override to publish the agent or Postgres ports.
- Real use of this project (a private instance with login and real data) is a different deployment; do not
  load real leads into the demo.
