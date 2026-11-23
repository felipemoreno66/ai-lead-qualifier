# n8n workflows

n8n is an **optional orchestrator**. With `ORCHESTRATOR=inline` (the default) nothing here is needed.

## Run it

```bash
ORCHESTRATOR=n8n COMPOSE_PROFILES=n8n docker compose up -d --build --wait
```

n8n is then on http://127.0.0.1:5678 (create the owner account on first visit). On every start
`entrypoint.sh` imports `workflows/*.json` and a local SMTP credential that points to Mailpit
(http://127.0.0.1:8025), then publishes the workflows. Nothing needs to be clicked.

## Workflows

| File | Trigger | What it does |
|---|---|---|
| `lead-created.json` | `POST /webhook/lead-created` (signed by the agent) | Verifies the HMAC signature, emails the owner a notification (reference and dashboard link, no personal data), then calls `POST /internal/events/{event_id}/ack` |

The webhook answers only after the whole workflow ran, so the agent marks the event delivered
only when n8n really processed it; any failure (bad signature, SMTP down) is retried with backoff.

## Security notes

- The agent signs the raw request body with `N8N_WEBHOOK_SECRET` (`X-Signature: sha256=...`).
  The first node verifies it in constant time.
- n8n calls the agent with `N8N_API_TOKEN` (`/internal/*` only).
- Workflows are committed **without credentials or execution data**. `scripts/sanitize_n8n.py`
  strips them and CI runs it in `--check` mode. After editing a workflow in the UI, export it and run
  `python scripts/sanitize_n8n.py n8n/workflows`.
- Execution data is not stored on success and is pruned after 7 days.
- `N8N_BLOCK_ENV_ACCESS_IN_NODE=false` lets the workflow read the secrets above from the environment.
  This is acceptable for a local, single-user instance; use n8n credentials for shared setups.
- The n8n database lives in the same Postgres server (`n8n` database, created on first start of a
  fresh volume).
