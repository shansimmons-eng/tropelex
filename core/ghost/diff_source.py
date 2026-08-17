"""
Ghost Detection — real diff sourcing (P4, closes the detection asymmetry
in gap C: prevention was wired, detection was not -- GET /ghost-decisions
and the scheduler's periodic scan both called detect_ghost_decisions with
diff_data hardcoded to [], which structurally can't detect anything).

Wraps git_integration's existing commit/diff helpers into the
[{file, diff_text}] shape detect_ghost_decisions expects, scoped to a
single project's own repo via memory["repo_path"] -- never falls back to
whichever repo Tropelex itself happens to be installed in.
"""

from typing import Any

from core.git_integration import (
    get_commit_diff,
    get_commits_since,
    get_project_repo_path,
    get_recent_commits,
    is_git_repo,
)


def recent_diffs(
    memory: dict[str, Any],
    since_ts: str | None = None,
    max_diffs: int = 50,
) -> list[dict[str, str]]:
    """Recent commit diffs for a project's own repo, as [{file, diff_text}].

    since_ts, if given, is passed to git's --since (a date/timestamp, not
    a commit ref) so a scheduled scan only re-fetches commits made after
    its last run. Without it, the most recent max_diffs commits are used
    (for on-demand calls with no prior-scan marker).

    Graceful: no repo_path recorded on this project, no git repo at that
    path, or no commits -> empty list, matching the tech_stack skip
    behavior _scan_ghost_decisions already has for projects with nothing
    to check.
    """
    repo_path = get_project_repo_path(memory)
    if not repo_path or not is_git_repo(repo_path):
        return []

    if since_ts:
        commits = get_commits_since(repo_path, since_ts)[:max_diffs]
    else:
        commits = get_recent_commits(repo_path, limit=max_diffs)

    diffs: list[dict[str, str]] = []
    for c in commits:
        diff_text = get_commit_diff(repo_path, c["hash"])
        if diff_text:
            diffs.append({"file": c["hash"], "diff_text": diff_text})
    return diffs
