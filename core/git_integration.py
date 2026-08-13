"""
Tropelex Git Integration
Auto-extracts decisions from commits, detects tech stack changes,
and records session context from git history.
"""

import json
import logging
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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

# Dependency files whose diffs signal tech stack changes
DEPENDENCY_FILES = {
    "requirements.txt",
    "pyproject.toml",
    "package.json",
    "Cargo.toml",
    "go.mod",
    "pom.xml",
    "build.gradle",
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
}

# File patterns mapped to work categories
FILE_CATEGORIES = {
    r"\.(css|scss|less|styled|style)": "ui",
    r"\.(tsx|jsx|vue|svelte|html)": "ui",
    r"(_test|_spec|\.test|\.spec)\.(ts|js|py|go|rs)": "testing",
    r"test_.*\.(py|ts|js)": "testing",
    r"\.github/workflows": "ci/cd",
    r"Dockerfile|docker-compose": "devops",
    r"\.(py|go|rs|java|rb|php)$": "backend",
    r"\.(ts|js)$": "backend",
    r"(migration|schema|prisma|sequelize)": "database",
    r"\.(json|yaml|yml|toml|ini|env)": "config",
    r"README|CHANGELOG|docs/": "documentation",
}

# Rationale signal words in commit bodies
RATIONALE_SIGNALS = [
    "because",
    "since",
    "due to",
    "in order to",
    "to fix",
    "to avoid",
    "to improve",
    "motivation:",
    "reason:",
    "context:",
    "this fixes",
    "this addresses",
    "workaround for",
    "previously",
]


def _run(cmd: list[str], cwd: str, timeout: int = 10) -> str | None:
    try:
        result = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout
        )
        return result.stdout.strip() if result.returncode == 0 else None
    except FileNotFoundError:
        logger.debug("Command not found: %s", cmd[0])
        return None
    except subprocess.TimeoutExpired:
        logger.debug("Command timed out: %s", " ".join(cmd))
        return None
    except OSError as e:
        logger.debug("Git command failed: %s — %s", " ".join(cmd), e)
        return None


def is_git_repo(path: str) -> bool:
    return _run(["git", "rev-parse", "--git-dir"], path) is not None


def get_project_repo_path(memory: dict[str, Any]) -> str | None:
    """Local filesystem path to a project's own repo, if it's ever been
    git-synced. Set by sync_repo_to_memory on every successful sync (unlike
    git_repo_fingerprint, which is set once and left alone as an identity
    check -- repo_path can legitimately move, e.g. a re-clone elsewhere).

    Filesystem-scoped features (Doc Mining, pytest count, git summary
    auto-load) use this to operate on THIS project's repo instead of
    silently falling back to whichever repo Tropelex itself happens to be
    installed in -- found live: a project ("cup") backed by a different
    repo entirely got Doc Mining findings and a pytest count sourced from
    Tropelex's own repo with no indication that's what happened.
    """
    path = memory.get("repo_path")
    if not isinstance(path, str) or not path:
        return None
    return path if Path(path).is_dir() else None


def get_repo_fingerprint(repo_path: str) -> str | None:
    """Return a stable identifier for the repo at `repo_path`.

    Prefers the `origin` remote URL (survives local moves/renames of the
    checkout); falls back to the root commit hash for remote-less repos
    (a fresh clone of the same remote still shares the root commit even
    if `origin` is missing or renamed).

    Used to detect when a project's git sync is pointed at a different
    repo than it was previously synced from — e.g. a stale/mistyped
    project-name field paired with the wrong repo_path, which otherwise
    silently mixes one repo's commit history into another project's
    memory with no warning.
    """
    remote = _run(["git", "remote", "get-url", "origin"], repo_path)
    if remote:
        return remote.strip()
    root_commit = _run(["git", "rev-list", "--max-parents=0", "HEAD"], repo_path)
    if root_commit:
        # A repo can have multiple roots (merged histories); take the first
        # deterministically rather than an arbitrary one from git's output order.
        return root_commit.splitlines()[0].strip()
    return None


def get_recent_commits(repo_path: str, limit: int = 20) -> list[dict[str, str]]:
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


def get_commit_body(repo_path: str, commit_hash: str) -> str:
    """Get the full commit message body (everything after subject)."""
    output = _run(
        ["git", "log", "-1", "--format=%b", commit_hash], repo_path
    )
    return output or ""


def get_commit_diffstat(repo_path: str, commit_hash: str) -> str:
    """Get diffstat summary for a commit (files changed, insertions/deletions)."""
    output = _run(
        ["git", "diff-tree", "--no-commit-id", "--stat", commit_hash], repo_path
    )
    return output or ""


def get_commit_diff(repo_path: str, commit_hash: str, max_lines: int = 200) -> str:
    """Get the actual diff for a commit, truncated to max_lines."""
    output = _run(
        ["git", "diff-tree", "-p", "--no-commit-id", commit_hash],
        repo_path,
        timeout=15,
    )
    if not output:
        return ""
    lines = output.splitlines()
    if len(lines) > max_lines:
        return "\n".join(lines[:max_lines]) + f"\n... ({len(lines) - max_lines} more lines)"
    return output


def get_commits_since(repo_path: str, since_ref: str) -> list[dict[str, str]]:
    """Get commits since a git ref (hash, tag, or date)."""
    fmt = "%H|||%s|||%an|||%ai"
    output = _run(
        ["git", "log", f"--since={since_ref}", f"--format={fmt}"], repo_path
    )
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
    commits: list[dict[str, str]],
) -> list[dict[str, str]]:
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
                # Extract body: remove prefix and optional scope like (scope)
                body = re.sub(
                    r"^" + prefix + r"(\([^)]*\))?:?\s*",
                    "",
                    subject,
                    flags=re.IGNORECASE,
                ).strip()
                context = f"From git commit {c['hash']} on {c['date']}"
                decisions.append(
                    {
                        "decision": f"{label}: {body}" if body else label,
                        "context": context,
                        "date": c["date"],
                        "hash": c["hash"],
                    }
                )
                break
    return decisions


def extract_deep_decisions(
    repo_path: str, commits: list[dict[str, str]], max_analyze: int = 20
) -> list[dict[str, Any]]:
    """
    Deep analysis of commits: parse bodies, classify files, detect rationale,
    and identify patterns like reverts and tech stack changes.
    """
    deep_decisions = []

    for c in commits[:max_analyze]:
        hash_ = c["hash"]
        subject = c["subject"]
        lower = subject.lower()
        body = get_commit_body(repo_path, hash_)
        changed_files = get_changed_files(repo_path, hash_)

        # 1. Extract rationale from commit body
        rationale = _extract_rationale(body)

        # 2. Classify what areas were touched
        categories = _classify_files(changed_files)

        # 3. Detect dependency changes
        dep_changes = _detect_dependency_changes(repo_path, hash_, changed_files)

        # 4. Detect revert chains
        is_revert = _is_revert(subject)
        reverts_what = _extract_revert_target(subject) if is_revert else None

        # 5. Detect pattern changes (new files, removed files, structural shifts)
        structural = _detect_structural_changes(changed_files)

        # Build the deep decision entry
        if any([rationale, dep_changes, is_revert, structural, categories]):
            entry: dict[str, Any] = {
                "hash": hash_,
                "subject": subject,
                "date": c["date"],
                "author": c["author"],
                "categories": categories,
                "files_changed": len(changed_files),
                "changed_files": changed_files[:10],  # cap for storage
            }

            if rationale:
                entry["rationale"] = rationale
            if dep_changes:
                entry["dependency_changes"] = dep_changes
            if is_revert:
                entry["is_revert"] = True
                if reverts_what:
                    entry["reverts"] = reverts_what
            if structural:
                entry["structural_changes"] = structural

            # Generate a human-readable decision summary
            entry["decision"] = _summarize_commit_decision(entry)
            entry["source"] = "git_deep"
            entry["context"] = (
                f"Deep analysis of commit {hash_} on {c['date']}"
            )

            deep_decisions.append(entry)

    return deep_decisions


def _extract_rationale(body: str) -> str | None:
    """Extract rationale/why from commit body text."""
    if not body:
        return None
    lines = body.strip().splitlines()
    rationale_lines = []
    for line in lines:
        lower = line.strip().lower()
        if any(signal in lower for signal in RATIONALE_SIGNALS):
            rationale_lines.append(line.strip())
        elif rationale_lines and line.strip() and not line.startswith(" "):
            # continuation of rationale
            rationale_lines.append(line.strip())
    return " ".join(rationale_lines) if rationale_lines else None


def _classify_files(files: list[str]) -> list[str]:
    """Classify changed files into work categories."""
    categories = set()
    for f in files:
        for pattern, cat in FILE_CATEGORIES.items():
            if re.search(pattern, f, re.IGNORECASE):
                categories.add(cat)
                break
    return sorted(categories)


def _detect_dependency_changes(
    repo_path: str, commit_hash: str, changed_files: list[str]
) -> list[dict[str, str]] | None:
    """Detect added/removed/updated dependencies from diff."""
    dep_files = [f for f in changed_files if Path(f).name in DEPENDENCY_FILES]
    if not dep_files:
        return None

    changes = []
    for dep_file in dep_files:
        diff = _run(
            ["git", "diff-tree", "-p", "--no-commit-id", commit_hash, "--", dep_file],
            repo_path,
            timeout=15,
        )
        if not diff:
            continue

        added = []
        removed = []
        for line in diff.splitlines():
            if line.startswith("+") and not line.startswith("+++"):
                added.append(line[1:].strip())
            elif line.startswith("-") and not line.startswith("---"):
                removed.append(line[1:].strip())

        if added or removed:
            changes.append({
                "file": dep_file,
                "added": added[:5],
                "removed": removed[:5],
            })

    return changes if changes else None


def _is_revert(subject: str) -> bool:
    """Check if commit is a revert."""
    lower = subject.lower()
    return any(kw in lower for kw in ["revert", "reverts", "undo", "roll back"])


def _extract_revert_target(subject: str) -> str | None:
    """Try to extract what commit/message is being reverted."""
    m = re.search(r"revert\s+[\"']?(.+?)[\"']?\s*$", subject, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    m = re.search(r"revert\s+([a-f0-9]{7,40})", subject, re.IGNORECASE)
    if m:
        return m.group(1)
    return None


def _detect_structural_changes(changed_files: list[str]) -> dict[str, Any] | None:
    """Detect structural patterns: new modules, migrations, tests added."""
    signals = {}

    new_dirs = set()
    for f in changed_files:
        parts = Path(f).parts
        if len(parts) > 1:
            new_dirs.add(parts[0])

    if new_dirs:
        signals["touched_areas"] = sorted(new_dirs)

    # Detect test additions
    test_files = [f for f in changed_files if re.search(r"test|spec", f, re.IGNORECASE)]
    if test_files:
        signals["tests_touched"] = len(test_files)

    # Detect migration additions
    migrations = [f for f in changed_files if "migration" in f.lower()]
    if migrations:
        signals["migrations"] = len(migrations)

    # Detect config changes
    config_files = [f for f in changed_files if re.search(r"\.(json|yaml|yml|toml|env)", f)]
    if config_files:
        signals["config_changes"] = len(config_files)

    return signals if signals else None


def _summarize_commit_decision(entry: dict[str, Any]) -> str:
    """Generate a one-line human-readable decision summary from a deep entry."""
    parts = []

    subject = entry.get("subject", "")
    cats = entry.get("categories", [])
    dep_changes = entry.get("dependency_changes", [])
    rationale = entry.get("rationale")

    # Clean subject
    clean = re.sub(r"^(feat|fix|refactor|chore|perf|revert)[:(][^)]*\)?:?\s*", "", subject, flags=re.IGNORECASE)
    parts.append(clean.strip() if clean.strip() else subject)

    if cats:
        parts.append(f"[{', '.join(cats)}]")

    if dep_changes:
        for dc in dep_changes:
            if dc.get("added"):
                parts.append(f"added {', '.join(dc['added'][:3])}")
            if dc.get("removed"):
                parts.append(f"removed {', '.join(dc['removed'][:3])}")

    if rationale:
        parts.append(f"— {rationale[:100]}")

    return " ".join(parts)


def detect_tech_stack(repo_path: str) -> list[str]:
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
    # Scan pyproject.toml
    pyproject = root / "pyproject.toml"
    if pyproject.exists():
        content = pyproject.read_text().lower()
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
        if "uvicorn" in content:
            found.add("FastAPI")
        if "pytest" in content:
            found.add("pytest")
        if "ruff" in content:
            found.add("Ruff")
        if "mypy" in content:
            found.add("mypy")
    # Scan package.json
    pkg = root / "package.json"
    if pkg.exists():
        try:
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
        except json.JSONDecodeError as exc:
            logger.warning("Corrupt package.json: %s", exc)
        except OSError as exc:
            logger.warning("Failed to read package.json: %s", exc)
    return sorted(found)


def detect_tech_stack_changes(
    repo_path: str, previous_stack: list[str]
) -> dict[str, Any]:
    """
    Compare current tech stack against what's in memory.
    Returns {added, removed, current}.
    """
    current = set(detect_tech_stack(repo_path))
    previous = set(previous_stack)
    return {
        "current": sorted(current),
        "added": sorted(current - previous),
        "removed": sorted(previous - current),
        "changed": bool(current != previous),
    }


def get_changed_files(repo_path: str, commit_hash: str) -> list[str]:
    """Files changed in a specific commit."""
    output = _run(
        ["git", "diff-tree", "--no-commit-id", "-r", "--name-only", commit_hash],
        repo_path,
    )
    return output.splitlines() if output else []


def get_current_branch(repo_path: str) -> str | None:
    return _run(["git", "branch", "--show-current"], repo_path)


def get_repo_summary(repo_path: str) -> dict[str, Any]:
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


def get_deep_repo_summary(repo_path: str, max_commits: int = 15) -> dict[str, Any]:
    """Enhanced repo summary with deep analysis of recent commits."""
    if not is_git_repo(repo_path):
        return {"error": "Not a git repository"}

    commits = get_recent_commits(repo_path, max_commits)
    shallow_decisions = extract_decisions_from_commits(commits)
    deep_decisions = extract_deep_decisions(repo_path, commits, max_commits)

    # Work category frequency from deep analysis
    category_freq: dict[str, int] = {}
    for d in deep_decisions:
        for cat in d.get("categories", []):
            category_freq[cat] = category_freq.get(cat, 0) + 1

    # Detect reverts
    reverts = [d for d in deep_decisions if d.get("is_revert")]

    return {
        "branch": get_current_branch(repo_path),
        "stack": detect_tech_stack(repo_path),
        "commits": commits[:5],
        "shallow_decisions": shallow_decisions,
        "deep_decisions": deep_decisions,
        "category_frequency": category_freq,
        "reverts": reverts,
        "total_commits_analyzed": len(commits),
    }


async def sync_repo_to_memory(
    repo_path: str, project_name: str, memory_manager, force: bool = False
) -> dict[str, Any]:
    """
    Pull git history into Tropelex memory for a project.
    - Updates tech_stack (with change detection)
    - Records new decisions from commits (shallow + deep)
    - Tracks revert chains
    - Returns summary of what was synced

    Guards against syncing the wrong repo into a project: on first sync,
    the repo's fingerprint (remote URL or root commit) is stored on the
    project. On every later sync, a fingerprint mismatch means repo_path
    points somewhere different than last time — returns synced=False with
    fingerprint_mismatch details instead of silently mixing that repo's
    commits into this project's memory, unless `force=True`.
    """
    if not is_git_repo(repo_path):
        return {"synced": False, "error": "Not a git repository"}

    memory = memory_manager.get_project_memory(project_name)

    fingerprint = get_repo_fingerprint(repo_path)
    existing_fingerprint = memory.get("git_repo_fingerprint")
    if fingerprint and existing_fingerprint and fingerprint != existing_fingerprint and not force:
        return {
            "synced": False,
            "fingerprint_mismatch": True,
            "error": (
                f"Project '{project_name}' was previously synced from a different repo "
                f"({existing_fingerprint}), but repo_path resolves to ({fingerprint}). "
                "Pass force=true to sync anyway if this is intentional."
            ),
            "previous_repo": existing_fingerprint,
            "current_repo": fingerprint,
        }

    commits = get_recent_commits(repo_path, 50)
    shallow_decisions = extract_decisions_from_commits(commits)
    deep_decisions = extract_deep_decisions(repo_path, commits, 25)
    stack = detect_tech_stack(repo_path)

    if fingerprint and not existing_fingerprint:
        memory["git_repo_fingerprint"] = fingerprint
    # Kept current on every sync (unlike the fingerprint identity check
    # above) -- a legitimate re-clone to a new path should update this.
    memory["repo_path"] = repo_path

    # Tech stack change detection
    existing_stack = memory.get("tech_stack", [])
    stack_changes = detect_tech_stack_changes(repo_path, existing_stack)
    memory["tech_stack"] = stack_changes["current"]

    # If tech stack changed, record it as a decision
    if stack_changes["changed"]:
        from datetime import datetime, timezone

        ts = datetime.now(timezone.utc).isoformat()
        if stack_changes["added"]:
            memory.setdefault("decisions", []).append({
                "timestamp": ts,
                "decision": f"Tech stack additions: {', '.join(stack_changes['added'])}",
                "context": "Auto-detected from dependency files",
                "source": "git_stack",
            })
        if stack_changes["removed"]:
            memory.setdefault("decisions", []).append({
                "timestamp": ts,
                "decision": f"Tech stack removals: {', '.join(stack_changes['removed'])}",
                "context": "Auto-detected from dependency files",
                "source": "git_stack",
            })

    # Record shallow decisions (skip duplicates by hash)
    existing_hashes = {
        d.get("hash") for d in memory.get("decisions", []) if "hash" in d
    }
    new_shallow = []
    for d in shallow_decisions:
        if d["hash"] not in existing_hashes:
            new_shallow.append({
                "timestamp": d["date"] + "T00:00:00+00:00",
                "decision": d["decision"],
                "context": d["context"],
                "hash": d["hash"],
                "source": "git",
            })
            existing_hashes.add(d["hash"])

    # Record deep decisions (skip duplicates by hash)
    new_deep = []
    for d in deep_decisions:
        if d["hash"] not in existing_hashes:
            entry = {
                "timestamp": d["date"] + "T00:00:00+00:00",
                "decision": d["decision"],
                "context": d.get("context", ""),
                "hash": d["hash"],
                "source": "git_deep",
            }
            if d.get("rationale"):
                entry["rationale"] = d["rationale"]
            if d.get("categories"):
                entry["categories"] = d["categories"]
            if d.get("dependency_changes"):
                entry["dependency_changes"] = d["dependency_changes"]
            if d.get("is_revert"):
                entry["is_revert"] = True
                if d.get("reverts"):
                    entry["reverts"] = d["reverts"]
            new_deep.append(entry)
            existing_hashes.add(d["hash"])

    memory.setdefault("decisions", []).extend(new_shallow)
    memory.setdefault("decisions", []).extend(new_deep)

    # Track work category patterns from deep analysis
    category_freq: dict[str, int] = {}
    for d in deep_decisions:
        for cat in d.get("categories", []):
            category_freq[cat] = category_freq.get(cat, 0) + 1

    # Update patterns with category frequencies
    if category_freq:
        from core.learner.learner import PatternLearner

        learner = PatternLearner(memory_manager)
        for cat, count in category_freq.items():
            for _ in range(count):
                learner._increment_pattern(memory, f"category:{cat}")

    from datetime import datetime, timezone

    memory["last_updated"] = datetime.now(timezone.utc).isoformat()
    memory_manager.save_project_memory(project_name, memory)

    return {
        "synced": True,
        "new_decisions": len(new_shallow) + len(new_deep),
        "shallow_decisions": len(new_shallow),
        "deep_decisions": len(new_deep),
        "stack_changes": stack_changes,
        "work_categories": category_freq,
        "stack": memory["tech_stack"],
        "branch": get_current_branch(repo_path),
    }
