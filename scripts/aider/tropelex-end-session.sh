#!/usr/bin/env bash
# End session and trigger pattern learning.
# Usage: scripts/aider/tropelex-end-session.sh "<summary>"
# Invoked from an Aider session via:
#   /run scripts/aider/tropelex-end-session.sh "Shipped the login flow"
#
# Mutating calls to Tropelex require the instance shared secret unless the
# request is same-origin (core/tropebook/web/server.py's
# instance_auth_middleware) -- a raw curl call never is, so this needs
# TROPEL_EX_SECRET set in the environment (the same value from Tropelex's
# own .env). Without it the call gets a 401 and this script says so plainly
# instead of claiming success the way a bare `curl ... && echo done` would.
set -euo pipefail

if [ $# -lt 1 ]; then
    echo "Usage: $0 \"<summary>\"" >&2
    exit 1
fi
SUMMARY="$1"

DIRNAME=$(basename "$(pwd)")
PROJECT=$(curl -s "http://localhost:8766/api/memory" | python3 -c "
import sys, json
d = '$DIRNAME'.lower()
names = [p['name'] for p in json.load(sys.stdin).get('projects', [])]
print(next((n for n in names if n.lower() == d), '$DIRNAME'))
" 2>/dev/null || echo "$DIRNAME")

AUTH_HEADER=()
if [ -n "${TROPEL_EX_SECRET:-}" ]; then
    AUTH_HEADER=(-H "Authorization: Bearer $TROPEL_EX_SECRET")
fi

BODY=$(jq -n --arg s "$SUMMARY" --arg a "Aider" '{summary:$s,session_type:"manual",agent_name:$a}')
RESPONSE=$(curl -s -w '\n%{http_code}' -X POST "http://localhost:8766/api/memory/$PROJECT/sessions/record" \
  -H "Content-Type: application/json" "${AUTH_HEADER[@]}" -d "$BODY")
STATUS=$(echo "$RESPONSE" | tail -n1)
BODY_OUT=$(echo "$RESPONSE" | sed '$d')

if [ "$STATUS" -ge 200 ] && [ "$STATUS" -lt 300 ]; then
    echo "✓ Session recorded for project $PROJECT"
else
    echo "✗ Failed ($STATUS): $BODY_OUT" >&2
    if [ "$STATUS" -eq 401 ]; then
        echo "  Set TROPEL_EX_SECRET in your environment (see Tropelex's .env)." >&2
    fi
    exit 1
fi
