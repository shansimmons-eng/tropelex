#!/usr/bin/env bash
# Register a new project with Tropelex (description + tech stack).
# Usage: scripts/aider/tropelex-up.sh "<description>" ["<tech,stack,items>"]
# Invoked from an Aider session via:
#   /run scripts/aider/tropelex-up.sh "A FastAPI backend" "Python,FastAPI,pytest"
#
# Mutating calls to Tropelex require the instance shared secret unless the
# request is same-origin (core/tropebook/web/server.py's
# instance_auth_middleware) -- a raw curl call never is, so this needs
# TROPEL_EX_SECRET set in the environment (the same value from Tropelex's
# own .env). Without it the call gets a 401 and this script says so plainly
# instead of claiming success the way a bare `curl ... && echo done` would.
set -euo pipefail

DESCRIPTION="${1:-}"
IFS=',' read -ra TECH_ARR <<< "${2:-}"

DIRNAME=$(basename "$(pwd)")
PROJECT=$(curl -s "http://localhost:8766/api/memory" | python3 -c "
import sys, json
d = '$DIRNAME'.lower()
names = [p['name'] for p in json.load(sys.stdin).get('projects', [])]
print(next((n for n in names if n.lower() == d), ''))
" 2>/dev/null || echo "")

if [ -n "$PROJECT" ]; then
    echo "Project '$PROJECT' is already registered with Tropelex."
    exit 0
fi

AUTH_HEADER=()
if [ -n "${TROPEL_EX_SECRET:-}" ]; then
    AUTH_HEADER=(-H "Authorization: Bearer $TROPEL_EX_SECRET")
fi

TECH_JSON=$(printf '%s\n' "${TECH_ARR[@]}" | jq -R . | jq -s 'map(select(length > 0))')
BODY=$(jq -n --arg n "$DIRNAME" --arg d "$DESCRIPTION" --argjson t "$TECH_JSON" \
  '{project_name:$n,description:$d,tech_stack:$t}')
RESPONSE=$(curl -s -w '\n%{http_code}' -X POST "http://localhost:8766/api/memory" \
  -H "Content-Type: application/json" "${AUTH_HEADER[@]}" -d "$BODY")
STATUS=$(echo "$RESPONSE" | tail -n1)
BODY_OUT=$(echo "$RESPONSE" | sed '$d')

if [ "$STATUS" -ge 200 ] && [ "$STATUS" -lt 300 ]; then
    echo "✓ Project '$DIRNAME' registered with Tropelex"
else
    echo "✗ Failed ($STATUS): $BODY_OUT" >&2
    if [ "$STATUS" -eq 401 ]; then
        echo "  Set TROPEL_EX_SECRET in your environment (see Tropelex's .env)." >&2
    fi
    exit 1
fi
