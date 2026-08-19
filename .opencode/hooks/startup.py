#!/usr/bin/env python3
"""
OpenCode Startup Hook - Tropelex Integration
Automatically loads project context and injects it into the system prompt.
"""

import json
import sys
from pathlib import Path

import httpx


def get_project_name():
    """Extract project name from current working directory."""
    cwd = Path.cwd()
    # Use directory name as project name (lowercase to match memory file convention)
    return cwd.name.lower()


def get_tropelex_context(project_name: str) -> str:
    """Fetch project context from Tropelex server."""
    try:
        with httpx.Client(timeout=2.0) as client:
            response = client.get(
                f"http://localhost:8766/api/memory/{project_name}/context"
            )
            if response.status_code == 200:
                data = response.json()
                return data.get("context", "")
    except Exception as e:
        print(f"[Tropelex] Could not load context: {e}", file=sys.stderr)
    return ""


def ensure_project_exists(project_name: str):
    """Create project in Tropelex if it doesn't exist."""
    try:
        with httpx.Client(timeout=2.0) as client:
            # Try to get project
            response = client.get(f"http://localhost:8766/api/memory/{project_name}")
            if response.status_code == 404:
                # Create it
                client.post(
                    "http://localhost:8766/api/memory",
                    json={"project_name": project_name},
                )
                print(f"[Tropelex] Created project: {project_name}", file=sys.stderr)
    except Exception as e:
        print(f"[Tropelex] Project check failed: {e}", file=sys.stderr)


def main():
    """Main startup hook - injects Tropelex context."""
    project_name = get_project_name()

    # Ensure project exists
    ensure_project_exists(project_name)

    # Get context
    context = get_tropelex_context(project_name)

    if context:
        # Return context to be injected into system prompt
        print(f"\n# TROPELEX CONTEXT FOR: {project_name}\n", file=sys.stderr)
        print(context, file=sys.stderr)
        print("\n# END TROPELEX CONTEXT\n", file=sys.stderr)

        # Output for OpenCode to capture
        print(
            json.dumps(
                {
                    "action": "inject_context",
                    "project": project_name,
                    "context": context,
                }
            )
        )
    else:
        print(f"[Tropelex] No context available for {project_name}", file=sys.stderr)
        print(json.dumps({"action": "none", "project": project_name}))


if __name__ == "__main__":
    main()
