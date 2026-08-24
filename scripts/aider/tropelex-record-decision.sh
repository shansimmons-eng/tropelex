#!/usr/bin/env bash
# Record a decision in Tropelex memory.
# Usage: scripts/aider/tropelex-record-decision.sh "<decision>" "<safety_category>" ["<context>"]
#   safety_category: one of adversarial, alignment, general, governance, monitoring, robustness
# Invoked from an Aider session via:
#   /run scripts/aider/tropelex-record-decision.sh "Use Postgres" general "Better relational support"
#
# safety_category is required by the API, not defaulted -- verified live:
# omitting it gets a 422 with a suggested category attached rather than
# silently recording as "general". That's deliberate (a prior real bug let
# every uncategorized decision get silently tagged "general"), so this
# script doesn't paper over it with a default either.
#
# Mutating calls to Tropelex also require the instance shared secret unless
# the request is same-origin (core/tropebook/web/server.py's
# instance_auth_middleware) -- a raw curl call never is, so this needs
# TROPEL_EX_SECRET set in the environment (the same value from Tropelex's
# own .env). Without it the call gets a 401 and this script says so plainly
# instead of claiming success the way a bare `curl ... && echo done` would.
set -euo pipefail

if [ $# -lt 2 ]; then
    echo "Usage: $0 \"<decision>\" \"<safety_category>\" [\"<context>\"]" >&2
    echo "  safety_category: adversarial | alignment | general | governance | monitoring | robustness" >&2
    exit 1
fi
DECISION="$1"
CATEGORY="$2"
CONTEXT="${3:-From Aider session}"

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

BODY=$(jq -n --arg d "$DECISION" --arg c "$CONTEXT" --arg cat "$CATEGORY" \
  '{decision:$d,context:$c,safety_metadata:{safety_category:$cat}}')
RESPONSE=$(curl -s -w '\n%{http_code}' -X POST "http://localhost:8766/api/memory/$PROJECT/decisions" \
  -H "Content-Type: application/json" "${AUTH_HEADER[@]}" -d "$BODY")
STATUS=$(echo "$RESPONSE" | tail -n1)
BODY_OUT=$(echo "$RESPONSE" | sed '$d')

if [ "$STATUS" -ge 200 ] && [ "$STATUS" -lt 300 ]; then
    echo "✓ Decision recorded for project $PROJECT"
else
    echo "✗ Failed ($STATUS): $BODY_OUT" >&2
    if [ "$STATUS" -eq 401 ]; then
        echo "  Set TROPEL_EX_SECRET in your environment (see Tropelex's .env)." >&2
    fi
    exit 1
fi
