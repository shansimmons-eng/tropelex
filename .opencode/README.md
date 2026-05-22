# Tropelex + OpenCode Integration

This directory contains hooks and commands that integrate Tropelex with OpenCode.

## How It Works

### Startup Hook
- **Runs automatically** when OpenCode starts in this workspace
- **Detects project name** from directory name (`tropelex-test`)
- **Loads context** from Tropelex memory for this project
- **Injects context** into your system prompt automatically

### Slash Commands

Use these commands during your session:

#### `/record-decision`
Record a decision in project memory.

```
/record-decision Using PostgreSQL for database | Better JSON support
```

Format: `/record-decision <decision> | <context (optional)>`

#### `/end-session`
Summarize your work and trigger pattern learning.

```
/end-session Built user auth with JWT, added password reset flow
```

This analyzes your summary and learns patterns like:
- UI work vs backend work
- Bug fixes vs new features
- Performance improvements
- Security updates

#### `/tropelex-context`
View current project context.

```
/tropelex-context
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
