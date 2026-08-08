#!/usr/bin/env bash
# Reference pre-push hook. Not installed automatically.
#
# To enable: cp core/triggers/hooks/pre-push.sh .git/hooks/pre-push
#            chmod +x .git/hooks/pre-push
#
# Both checks currently run at severity="warn", so this never blocks a push
# on its own (see core/triggers/checks.py) — it prints findings and exits 0.
# Flip a check to severity="block" once you trust it enough to gate on.

set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
python3 -m core.triggers.cli pre_push
