# Accessibility Scanning

Automated WCAG checks via [axe-core](https://github.com/dequelabs/axe-core) (Deque), driven by [Playwright](https://playwright.dev/).

## Setup (one-time)

```bash
cd scripts/a11y
npm install
npx playwright install chromium   # only needed if not already cached
```

## Run

The dashboard must be running first:

```bash
python3 -m core.tropebook.web.server   # from the repo root, separate terminal
```

Then, from `scripts/a11y/`:

```bash
npm run scan
```

Point at a different dashboard URL (e.g. a non-default port):

```bash
A11Y_DASHBOARD_URL=http://localhost:9000/ npm run scan
```

## Output

Each run writes a full JSON report to `scripts/a11y/reports/a11y-report-<timestamp>.json` (gitignored — generated output, not checked in). The console prints a summary grouped by impact (`critical`/`serious`/`moderate`/`minor`) and every violation's rule id, description, affected node count, and a link to Deque's fix guidance. Exits non-zero if any violations were found, so this can gate CI.

## Coverage

Scans the dashboard's initial load plus every top-level sidebar section (Engine Core, Quality & Integrity, Explainability & Discovery, Safety & Alignment, Memory Lifecycle, Research & Ingestion, Team & Collaboration, Integrations & Ops, Getting Started, Settings), plus the static GitHub Pages site (`site/*.html`). Doesn't yet drill into every sub-tab *within* a section — expanding coverage means adding more navigation steps to `scan.mjs`, not a different tool.

## What this catches (and doesn't)

axe-core is a mechanical, automated checker — it catches roughly the [30-40% of WCAG issues that are programmatically detectable](https://www.deque.com/blog/automated-testing-study-identifies-57-percent-of-issues/): missing alt text/labels, insufficient color contrast, invalid ARIA usage, malformed heading structure, missing form labels. It does **not** replace:

- A manual keyboard-only pass (tab order, visible focus indicators, no keyboard traps).
- A real screen reader spot-check (VoiceOver on Mac, NVDA on Windows) — catches issues automated tools structurally can't, like an icon button that has *a* label but not a *meaningful* one, or content that reads in a confusing order despite passing every automated rule.

Treat a clean automated run as a floor, not a finish line.
