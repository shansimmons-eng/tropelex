# Tropelex scripts for Aider

Aider has no MCP support (confirmed: [Aider-AI/aider#4506](https://github.com/Aider-AI/aider/issues/4506)
is still open as of mid-2026, PRs closed unmerged) and no user-definable
slash commands — only a fixed built-in set. There's no Aider equivalent of
`.claude/commands/`, `.opencode/commands/`, or a `SKILL.md` folder.

The closest real hook is Aider's built-in `/run <command>`, which executes
a shell command and feeds its output back into the chat. These scripts wrap
the same Tropelex REST calls the other integrations use, so they work the
same way inside an Aider session:

```
/run scripts/aider/tropelex-show-context.sh
/run scripts/aider/tropelex-record-decision.sh "Use Postgres" general "Better relational support"
/run scripts/aider/tropelex-end-session.sh "Shipped the login flow"
/run scripts/aider/tropelex-up.sh "A FastAPI backend" "Python,FastAPI,pytest"
```

`tropelex-record-decision.sh` takes `safety_category` as a required second
argument (one of `adversarial`, `alignment`, `general`, `governance`,
`monitoring`, `robustness`) — the API rejects a decision with no category
rather than silently defaulting one, so this script doesn't paper over that
either.

Requires `jq` and `python3` on `PATH`, and the Tropelex server running at
`http://localhost:8766` (`python3 -m core.tropebook.web.server`).

The three write scripts (`record-decision`, `end-session`, `up`) also need
`TROPEL_EX_SECRET` set in your shell environment — Tropelex requires the
instance shared secret on every mutating call that isn't a same-origin
browser request (`core/tropebook/web/server.py`'s `instance_auth_middleware`),
and a raw curl call from `/run` never qualifies. Get the value from
Tropelex's own `.env` and export it before starting Aider:

```
export TROPEL_EX_SECRET=$(grep '^TROPEL_EX_SECRET=' /path/to/Tropelex/.env | cut -d= -f2-)
```

Without it, these scripts fail loudly with the actual HTTP status instead
of claiming success — verified live: an earlier version of this script
used a bare `curl ... && echo done`, which prints success unconditionally
because curl exits 0 even on a 401 response. Caught by actually running it
against the real server before calling this finished, not by inspection.

This is a workaround, not a native command — if Aider ever ships MCP
support, these scripts should be replaced by a proper MCP-prompt-based
integration like the one Devin/Gemini CLI/Zed already get for free from
`mcp_server/server.py`.
