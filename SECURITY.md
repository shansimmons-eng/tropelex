# Security Policy

This document is about **vulnerability disclosure** — bugs that could let
someone bypass a security control, leak data, or run something they
shouldn't. For AI safety and alignment properties (drift detection, decision
gates, audit trails), see [SAFETY.md](SAFETY.md) instead — different concern,
different document.

## Supported versions

Tropelex doesn't maintain parallel release branches. The latest commit on
`main` is the only version that gets security fixes; there's no backport
policy for older tags.

## Reporting a vulnerability

**Please don't open a public issue for a security vulnerability.** Use
GitHub's private vulnerability reporting instead:

1. Go to the [Security tab](https://github.com/shansimmons-eng/tropelex/security) of this repo.
2. Click **Report a vulnerability**.
3. Describe the issue, how to reproduce it, and its impact as concretely as
   you can.

This opens a private advisory only you and the maintainer can see until it's
resolved — no email address to guess, and no public exposure while a fix is
in progress.

If you don't have a GitHub account or the private-reporting flow doesn't
work for you, open a regular issue that says only "possible security issue,
please contact me" with no technical detail, and a way to reach you; details
can follow privately.

## What's actually in scope

Tropelex runs entirely locally by default (`localhost:8766`, no external
service). Realistic vulnerability classes for this project look like:

- Authentication/authorization bypass on the instance shared-secret
  (`core/auth/shared_secret.py`)
- Path traversal or injection in any endpoint that touches the filesystem
  (`memory/`, feed storage, Repo Seek batches)
- SSRF in anything that fetches a URL on the caller's behalf (research
  providers, citation import)
- XSS in the dashboard (`UI/animated_tropebook_dashboard/code.html`) via
  unsanitized citation/decision content
- A way to make the audit log or decision content hash (both
  `core/audit.py`) accept a forged or silently-tampered entry

Reports about things that are already disclosed, expected behavior — e.g.
"the server has no auth by default when run purely on localhost with no
port exposed" — are welcome context but not novel findings; check
[SAFETY.md](SAFETY.md) and this file first if you're not sure something is
already a known tradeoff.

## Response

This is a single-maintainer project. There's no SLA, but reports get read
and taken seriously — expect an initial response, not necessarily an
immediate fix.
