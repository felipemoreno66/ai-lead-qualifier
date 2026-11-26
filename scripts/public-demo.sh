#!/usr/bin/env bash
# Manage the public demo (project "alq-demo"). It never touches Tailscale Funnel: publishing to the
# internet is a separate, explicit step (see docs/deploy-public-demo.md).
#   scripts/public-demo.sh init | up | status | reset | logs | down | destroy
set -euo pipefail

cd "$(dirname "$0")/.."
ENV_FILE=".env.public"
COMPOSE=(docker compose -p alq-demo --env-file "$ENV_FILE" -f docker-compose.yml -f docker-compose.public.yml)

need_env() {
  [[ -f "$ENV_FILE" ]] || { echo "Missing $ENV_FILE. Run: scripts/public-demo.sh init" >&2; exit 1; }
}

secret() { openssl rand -hex 24; }

# set_var NAME VALUE: replace the NAME= line of .env.public
set_var() {
  local name=$1 value=$2
  sed -i "s|^${name}=.*|${name}=${value}|" "$ENV_FILE"
}

tailscale_url() {
  command -v tailscale >/dev/null 2>&1 || return 0
  tailscale status --json 2>/dev/null | python3 -c '
import json, sys
try:
    name = json.load(sys.stdin)["Self"]["DNSName"].rstrip(".")
    print("https://" + name if name else "")
except Exception:
    pass
' || true
}

web_port() {
  local port
  port=$(grep -E '^DEMO_WEB_PORT=[0-9]+' "$ENV_FILE" | cut -d= -f2 || true)
  echo "${port:-3000}"
}

cmd_init() {
  [[ ! -f "$ENV_FILE" ]] || { echo "$ENV_FILE already exists; leaving it untouched."; return; }
  cp .env.public.example "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  for name in POSTGRES_PASSWORD ADMIN_API_TOKEN N8N_API_TOKEN N8N_WEBHOOK_SECRET IP_HASH_SECRET; do
    set_var "$name" "$(secret)"
  done
  local url
  url=$(tailscale_url)
  if [[ -n "$url" ]]; then
    set_var PUBLIC_URL "$url"
    echo "PUBLIC_URL set to $url (from tailscale status)."
  else
    echo "Could not detect the Tailscale name. Set PUBLIC_URL in $ENV_FILE (https://<machine>.<tailnet>.ts.net)."
  fi
  echo "Created $ENV_FILE with generated secrets (mode 600, gitignored)."
}

cmd_up() {
  need_env
  if ! grep -Eq '^PUBLIC_URL=https://.+' "$ENV_FILE"; then
    echo "Set PUBLIC_URL=https://<machine>.<tailnet>.ts.net in $ENV_FILE first." >&2
    exit 1
  fi
  "${COMPOSE[@]}" up -d --build
  local port
  port=$(web_port)
  echo "Waiting for the web app (the first start downloads the embedding model, a few minutes)..."
  for _ in $(seq 1 120); do
    if curl -fsS -o /dev/null "http://127.0.0.1:${port}/"; then
      echo "Demo is up locally: http://127.0.0.1:${port}"
      echo "To publish it (you run this, it goes on the internet): tailscale funnel --bg ${port}"
      return
    fi
    sleep 5
  done
  echo "Timed out; check: scripts/public-demo.sh logs" >&2
  exit 1
}

cmd_status() {
  need_env
  "${COMPOSE[@]}" ps
  echo
  if command -v tailscale >/dev/null 2>&1; then tailscale funnel status || true; fi
}

cmd_reset() {
  need_env
  "${COMPOSE[@]}" exec demo-reset python -m lead_qualifier.scripts.demo_reset --once
}

cmd_logs() {
  need_env
  "${COMPOSE[@]}" logs -f --tail=100 "$@"
}

cmd_down() {
  need_env
  "${COMPOSE[@]}" down
  echo "Stopped (data kept). To unpublish: tailscale funnel --https=443 off"
}

cmd_destroy() {
  need_env
  "${COMPOSE[@]}" down --volumes
  echo "Stopped and data deleted."
}

case "${1:-}" in
  init) cmd_init ;;
  up) cmd_up ;;
  status) cmd_status ;;
  reset) cmd_reset ;;
  logs) shift; cmd_logs "$@" ;;
  down) cmd_down ;;
  destroy) cmd_destroy ;;
  *) echo "Usage: $0 {init|up|status|reset|logs|down|destroy}" >&2; exit 2 ;;
esac
