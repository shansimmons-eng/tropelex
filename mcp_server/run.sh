#!/usr/bin/env bash
# Portable launcher for the Tropelex MCP server — resolves its own directory
# so project-scoped .mcp.json can reference it with a relative path that
# works regardless of where the repo is cloned.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ ! -x "$SCRIPT_DIR/.venv/bin/python" ]; then
    echo "tropelex-mcp: venv not found at $SCRIPT_DIR/.venv — run:" >&2
    echo "  cd $SCRIPT_DIR && uv venv .venv && uv pip install --python .venv/bin/python -r requirements.txt" >&2
    exit 1
fi

exec "$SCRIPT_DIR/.venv/bin/python" "$SCRIPT_DIR/server.py"
