"""
Tropelex Git Integration
Auto-extracts decisions from commits, detects tech stack changes,
and records session context from git history.
"""

import re
import subprocess
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any

logger = logging.getLogger("tropelex.git")

# Commit prefixes that signal architectural decisions worth recording
DECISION_PREFIXES = {
    "refactor": "Refactored",
    "feat": "Added feature",
    "fix": "Fixed",
    "chore": "Changed",
    "perf": "Optimised",
    "security": "Security change",
    "revert": "Reverted",
    "breaking": "Breaking change",
    "migrate": "Migrated",
    "switch": "Switched",
    "replace": "Replaced",
    "remove": "Removed",
    "add": "Added",
}

# Files that indicate tech stack
STACK_SIGNALS = {
    "requirements.txt": "Python",
    "pyproject.toml": "Python",
    "package.json": "Node.js",
    "Cargo.toml": "Rust",
    "go.mod": "Go",
    "pom.xml": "Java/Maven",
    "build.gradle": "Java/Gradle",
    "Dockerfile": "Docker",
    "docker-compose.yml": "Docker Compose",
    ".github/workflows": "GitHub Actions",
    "tailwind.config.js": "Tailwind CSS",
    "vite.config.ts": "Vite",
    "next.config.js": "Next.js",
    "svelte.config.js": "Svelte",
    "fastapi": "FastAPI",
    "uvicorn": "FastAPI",
    "prisma": "Prisma",
}


def _run(cmd: List[str], cwd: str) -> Optional[str]:
    try:
        result = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, timeout=10
        )
        return result.stdout.strip() if result.returncode == 0 else None
    except Exception as e:
        logger.debug("Git command failed: %s — %s", " ".join(cmd), e)
        return None


def is_git_repo(path: str) -> bool:
    return _run(["git", "rev-parse", "--git-dir"], path) is not None


def get_recent_commits(repo_path: str, limit: int = 20) -> List[Dict[str, str]]:
    """Return recent commits as [{hash, subject, author, date}]."""
    fmt = "%H|||%s|||%an|||%ai"
    output = _run(["git", "log", f"-{limit}", f"--format={fmt}"], repo_path)
    if not output:
        return []
    commits = []
    for line in output.splitlines():
        parts = line.split("|||")
        if len(parts) == 4:
            commits.append(
                {
                    "hash": parts[0][:8],
                    "subject": parts[1],
                    "author": parts[2],
                    "date": parts[3][:10],
                }
            )
    return commits


def extract_decisions_from_commits(
    commits: List[Dict[str, str]],
) -> List[Dict[str, str]]:
    """
    Filter commits that look like architectural decisions.
    Returns [{decision, context, date}]
    """
    decisions = []
    for c in commits:
        subject = c["subject"]
        lower = subject.lower()
        for prefix, label in DECISION_PREFIXES.items():
            if lower.startswith(prefix + ":") or lower.startswith(prefix + "("):
                # Extract the reason if present (after " — " or " because " or " to ")
                body = re.sub(
                    r"^" + prefix + r"[:(][^)]*\)?:?\s*",
                    "",
                    subject,
                    flags=re.IGNORECASE,
                ).strip()
                context = f"From git commit {c['hash']} on {c['date']}"
                decisions.append(
                    {
                        "decision": f"{label}: {body}",
                        "context": context,
                        "date": c["date"],
                        "hash": c["hash"],
                    }
                )
                break
    return decisions


def detect_tech_stack(repo_path: str) -> List[str]:
    """Detect tech stack by inspecting files in the repo."""
    found = set()
    root = Path(repo_path)
    for signal, tech in STACK_SIGNALS.items():
        if (root / signal).exists():
            found.add(tech)
    # Also scan requirements.txt for key packages
    req = root / "requirements.txt"
    if req.exists():
        content = req.read_text().lower()
        if "fastapi" in content:
            found.add("FastAPI")
        if "django" in content:
            found.add("Django")
        if "flask" in content:
            found.add("Flask")
        if "sqlalchemy" in content:
            found.add("SQLAlchemy")
        if "pydantic" in content:
            found.add("Pydantic")
        if "httpx" in content:
            found.add("httpx")
        if "openai" in content:
            found.add("OpenAI API")
    # Scan package.json
    pkg = root / "package.json"
    if pkg.exists():
        try:
            import json

            deps = json.loads(pkg.read_text())
            all_deps = {
                **deps.get("dependencies", {}),
                **deps.get("devDependencies", {}),
            }
            if "react" in all_deps:
                found.add("React")
            if "vue" in all_deps:
                found.add("Vue")
            if "svelte" in all_deps:
                found.add("Svelte")
            if "tailwindcss" in all_deps:
                found.add("Tailwind CSS")
            if "typescript" in all_deps:
                found.add("TypeScript")
            if "next" in all_deps:
                found.add("Next.js")
        except Exception:
            pass
    return sorted(found)


def get_changed_files(repo_path: str, commit_hash: str) -> List[str]:
    """Files changed in a specific commit."""
    output = _run(
        ["git", "diff-tree", "--no-commit-id", "-r", "--name-only", commit_hash],
        repo_path,
    )
    return output.splitlines() if output else []


def get_current_branch(repo_path: str) -> Optional[str]:
    return _run(["git", "branch", "--show-current"], repo_path)


def get_repo_summary(repo_path: str) -> Dict[str, Any]:
    """Return a summary dict useful for memory injection."""
    if not is_git_repo(repo_path):
        return {"error": "Not a git repository"}
    commits = get_recent_commits(repo_path, 30)
    return {
        "branch": get_current_branch(repo_path),
        "stack": detect_tech_stack(repo_path),
        "commits": commits[:5],  # most recent 5 for display
        "decisions": extract_decisions_from_commits(commits),
    }


async def sync_repo_to_memory(
    repo_path: str, project_name: str, memory_manager
) -> Dict[str, Any]:
    """
    Pull git history into Tropelex memory for a project.
    - Updates tech_stack
    - Records new decisions from commits
    - Returns summary of what was synced
    """
    if not is_git_repo(repo_path):
        return {"synced": False, "error": "Not a git repository"}

    commits = get_recent_commits(repo_path, 50)
    decisions = extract_decisions_from_commits(commits)
    stack = detect_tech_stack(repo_path)

    memory = memory_manager.get_project_memory(project_name)

    # Update tech stack (merge, no duplicates)
    existing_stack = set(memory.get("tech_stack", []))
    for tech in stack:
        if tech not in existing_stack:
            existing_stack.add(tech)
    memory["tech_stack"] = sorted(existing_stack)

    # Record new decisions (skip duplicates by hash)
    existing_hashes = {
        d.get("hash") for d in memory.get("decisions", []) if "hash" in d
    }
    new_decisions = []
    for d in decisions:
        if d["hash"] not in existing_hashes:
            new_decisions.append(
                {
                    "timestamp": d["date"] + "T00:00:00+00:00",
                    "decision": d["decision"],
                    "context": d["context"],
                    "hash": d["hash"],
                    "source": "git",
                }
            )
            existing_hashes.add(d["hash"])

    memory.setdefault("decisions", []).extend(new_decisions)

    from datetime import datetime, timezone

    memory["last_updated"] = datetime.now(timezone.utc).isoformat()
    memory_manager.save_project_memory(project_name, memory)

    return {
        "synced": True,
        "new_decisions": len(new_decisions),
        "stack": memory["tech_stack"],
        "branch": get_current_branch(repo_path),
    }
