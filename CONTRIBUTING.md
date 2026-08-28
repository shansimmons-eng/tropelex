# Contributing to Tropelex

Thanks for taking a look. This has been a solo project up to now, so if you're
reading this to make a first contribution, you're likely one of the first —
expect fast, direct feedback rather than a heavy process.

## Before you start

For anything more than a typo fix, open an issue first describing what you
want to change and why. It's a much smaller cost than writing a PR that turns
out to be solving the wrong problem, or duplicating something already
in [`wishlist.md`](wishlist.md).

## Development setup

```bash
git clone https://github.com/shansimmons-eng/tropelex.git
cd tropelex
uv venv
uv pip install -r requirements.txt
python -m core.tropebook.web.server
```

See [Getting Started](https://shansimmons-eng.github.io/tropelex/getting-started.html)
for the full walkthrough, including optional API keys.

## Testing mandate

**Every new feature, bug fix, or API endpoint must have tests before it's
considered done.** This is enforced by a pre-push hook, not just a guideline:

- New endpoint → add tests in `tests/` using `TestClient` (`tests/test_compaction.py`
  is a representative pattern)
- New model field → add roundtrip, validation, and default tests
- Bug fix → add a regression test that fails without the fix
- New module → a corresponding `tests/test_<module>.py`

```bash
pytest tests/ -x -q
```

`last30days` engine tests consume external API tokens and are excluded by
default (`@pytest.mark.last30days`); run them explicitly with
`pytest -m last30days` only if you're touching that engine.

## Code style

Ruff handles both linting and import sorting, configured in `pyproject.toml`:

```bash
ruff check .
```

Match the conventions already in the file you're editing rather than
introducing a new pattern for the same problem — this codebase leans on a few
repeated shapes (`Result`/`Ok`/`Err` for pure functions, explicit
`require_*` gates over silent defaults, hash-chained audit events for
anything safety-relevant) rather than one-off solutions per feature.

## Pull requests

- Keep PRs scoped to one change. A bug fix doesn't need an accompanying
  refactor.
- Explain the *why*, not just the *what* — the reasoning is what future
  readers (human or agent) actually need; the diff already shows the what.
- Reference the issue it resolves, if there is one.

## Reporting a security issue

Don't open a public issue for a vulnerability — see [SECURITY.md](SECURITY.md)
for how to report it privately instead.

## Questions

Open an issue, or check the [FAQ](https://shansimmons-eng.github.io/tropelex/faq.html)
first in case it's already answered there.
