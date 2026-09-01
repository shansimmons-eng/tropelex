"""
Instance identity -- a public, non-secret identifier for this Tropelex
install, distinct from core.auth.shared_secret's TROPEL_EX_SECRET (a
credential that must never leave the machine).

This ID is specifically meant to travel with exported data: account
export/import (core/tropebook/web/server.py), benchmarks export/import
(core/benchmarks/router.py), and sync export/import (core/sync/) all
stamp it into what they produce, so a receiving install can record which
install a given piece of data actually came from -- provenance across
installs that share data, not authentication. Never used for access
control; leaking it grants nothing.

Mirrors core.auth.shared_secret.get_or_create_secret's exact persistence
pattern (generate once, write to <base_dir>/.env, read from the
environment on every later call) so the two concepts stay consistent
without being the same value.
"""

from __future__ import annotations

import logging
import os
import secrets
from pathlib import Path

logger = logging.getLogger("tropelex.identity")

INSTANCE_ID_ENV_VAR = "TROPELEX_INSTANCE_ID"


def get_or_create_instance_id(base_dir: Path) -> str:
    """Return this install's instance id, generating and persisting one
    to <base_dir>/.env on first run. Idempotent across restarts, same
    shape as get_or_create_secret: once written, the .env loader in
    server.py picks it up via os.environ.setdefault before this ever
    runs again.
    """
    existing = os.environ.get(INSTANCE_ID_ENV_VAR, "")
    if existing:
        return existing

    instance_id = secrets.token_hex(8)
    os.environ[INSTANCE_ID_ENV_VAR] = instance_id

    env_path = base_dir / ".env"
    try:
        with open(env_path, "a") as f:
            f.write(f"\n{INSTANCE_ID_ENV_VAR}={instance_id}\n")
        logger.info(
            "Generated new instance id and wrote it to %s (%s). This value is not a "
            "secret -- it's stamped into exports to preserve provenance across installs.",
            env_path, instance_id,
        )
    except OSError as exc:
        logger.error(
            "Could not persist %s to %s: %s. A new instance id will be generated on "
            "every restart until this is fixed, which will change how exported data "
            "from this install is attributed each time.",
            INSTANCE_ID_ENV_VAR, env_path, exc,
        )
    return instance_id
