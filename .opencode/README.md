# Tropelex + OpenCode Integration

This directory contains hooks and commands that integrate Tropelex with OpenCode.

## How It Works

### Startup Hook (`hooks/startup.py`): not currently wired up
This script detects the project name from the directory and loads Tropelex
context, but OpenCode only auto-runs plugins placed in `.opencode/plugins/`
using the `@opencode-ai/plugin` SDK (JS/TS): a standalone Python file here
is never invoked automatically. Use `/tropelex-show-context` manually to get
the same effect until this is ported to a real plugin.

### Slash Commands

OpenCode auto-discovers any `.md` file in this directory as a slash command
named after the file: no config needed, nothing to register. The commands
actually present here:

#### `/tropelex-record-decision`
Record a decision in project memory.

```
/tropelex-record-decision Using PostgreSQL for database | Better JSON support
```

Format: `/tropelex-record-decision <decision> | <context (optional)>`

#### `/tropelex-end-session`
Summarize your work and trigger pattern learning.

```
/tropelex-end-session Built user auth with JWT, added password reset flow
```

This analyzes your summary and learns patterns like:
- UI work vs backend work
- Bug fixes vs new features
- Performance improvements
- Security updates

#### `/tropelex-show-context`
View current project context.

```
/tropelex-show-context
```

Shows all accumulated knowledge for this project.

## Setup

1. **Start Tropelex server**: 
   ```bash
   cd ~/tropelex-test
   uv run python -m core.tropebook.web.server
   ```

2. **Use OpenCode** in this directory - context loads automatically

3. **Record as you work**:
   - Make decision → `/record-decision <what you decided>`
   - End session → `/end-session <what you built>`
   - View context → `/tropelex-context`

## Project Association

The project name is automatically derived from your workspace folder name:
- Working in `~/tropelex-test` → project name is `tropelex-test`
- Working in `~/my-app` → project name is `my-app`

Each workspace gets its own isolated memory in Tropelex.

## Requirements

- Tropelex server running on `localhost:8766`
- `httpx` installed (`uv pip install httpx`)
- Python 3.8+
