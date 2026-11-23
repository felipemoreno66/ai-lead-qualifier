#!/bin/sh
# Imports the committed workflows on every start (idempotent), publishes them, then runs n8n.
set -e
node /opt/leadq/prepare.js
n8n import:credentials --input=/tmp/n8n-import/credentials.json
n8n import:workflow --separate --input=/tmp/n8n-import/workflows
for f in /tmp/n8n-import/workflows/*.json; do
  id=$(node -p "require('$f').id")
  n8n publish:workflow --id="$id"
done
exec n8n start
