#!/usr/bin/env bash
# Show Tropelex's accumulated context for the current project.
# Aider has no MCP support and no user-definable slash commands (confirmed:
# github.com/Aider-AI/aider#4506, still open as of mid-2026) -- this script
# is the closest equivalent, invoked from an Aider session via:
#   /run scripts/aider/tropelex-show-context.sh
set -euo pipefail

DIRNAME=$(basename "$(pwd)")
PROJECT=$(curl -s "http://localhost:8766/api/memory" | python3 -c "
import sys, json
d = '$DIRNAME'.lower()
names = [p['name'] for p in json.load(sys.stdin).get('projects', [])]
print(next((n for n in names if n.lower() == d), '$DIRNAME'))
" 2>/dev/null || echo "$DIRNAME")

curl -s "http://localhost:8766/api/memory/$PROJECT/context" | python3 -c "
import sys, json
data = json.load(sys.stdin)
print(data.get('context', 'No context available'))
" 2>/dev/null || echo "Tropelex server not reachable"
