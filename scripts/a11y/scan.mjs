#!/usr/bin/env node
/**
 * Repeatable WCAG accessibility scan for Tropelex.
 *
 * Scans the live dashboard (initial load + every top-level sidebar
 * section) and the static GitHub Pages site (site/*.html), via axe-core
 * (Deque's automated WCAG checker) driven by Playwright. Writes a full
 * JSON report per run and prints a console summary grouped by impact.
 *
 * Automated checks only catch a fraction of real accessibility issues --
 * see README.md's "What this catches (and doesn't)" section before
 * treating a clean run as "fully accessible."
 *
 * Usage:
 *   npm install && npx playwright install chromium   # one-time setup
 *   npm run scan                                     # dashboard must be
 *                                                     # running first
 *   A11Y_DASHBOARD_URL=http://localhost:9000/ npm run scan
 */

import { chromium } from "playwright";
import AxeBuilder from "@axe-core/playwright";
import { writeFileSync, mkdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(__dirname, "..", "..");
const OUT_DIR = path.join(__dirname, "reports");

const DASHBOARD_URL = process.env.A11Y_DASHBOARD_URL || "http://localhost:8766/";

// Top-level sidebar sections (see UI/animated_tropebook_dashboard/code.html's
// switchSection() and each nav-item's data-section). Doesn't drill into every
// sub-tab within a section yet -- expanding coverage means adding more
// navigation steps below, not a different tool.
const SECTIONS = [
  "content", "quality", "explainability", "safety", "lifecycle",
  "research", "team", "integrations", "onboarding", "settings",
];

const STATIC_PAGES = [
  "site/index.html",
  "site/getting-started.html",
  "site/faq.html",
  "site/api-reference.html",
].map((p) => "file://" + path.join(REPO_ROOT, p));

async function scanCurrentPage(page, label) {
  const results = await new AxeBuilder({ page }).analyze();
  return {
    label,
    url: page.url(),
    timestamp: new Date().toISOString(),
    violations: results.violations,
    passes: results.passes.length,
    incomplete: results.incomplete.length,
  };
}

async function main() {
  mkdirSync(OUT_DIR, { recursive: true });
  const browser = await chromium.launch();
  const context = await browser.newContext();
  const page = await context.newPage();
  const allResults = [];

  try {
    await page.goto(DASHBOARD_URL, { waitUntil: "networkidle", timeout: 15000 });
    allResults.push(await scanCurrentPage(page, "dashboard:overview"));
    for (const section of SECTIONS) {
      await page.evaluate((s) => {
        if (typeof window.switchSection === "function") window.switchSection(s);
      }, section);
      await page.waitForTimeout(300); // let the section's own async loaders settle
      allResults.push(await scanCurrentPage(page, `dashboard:${section}`));
    }
  } catch (err) {
    console.error(
      `Dashboard scan skipped/incomplete -- is it running at ${DASHBOARD_URL}? (${err.message})`,
    );
  }

  for (const url of STATIC_PAGES) {
    try {
      await page.goto(url, { waitUntil: "load", timeout: 15000 });
      allResults.push(await scanCurrentPage(page, url));
    } catch (err) {
      console.error(`Static page scan failed for ${url}: ${err.message}`);
    }
  }

  await browser.close();

  const reportPath = path.join(OUT_DIR, `a11y-report-${new Date().toISOString().slice(0, 19).replace(/:/g, "-")}.json`);
  writeFileSync(reportPath, JSON.stringify(allResults, null, 2));

  const byImpact = { critical: 0, serious: 0, moderate: 0, minor: 0 };
  let totalViolations = 0;
  for (const r of allResults) {
    for (const v of r.violations) {
      totalViolations += 1;
      byImpact[v.impact] = (byImpact[v.impact] || 0) + 1;
    }
  }

  console.log(`\nScanned ${allResults.length} view(s). Total violations: ${totalViolations}`);
  console.log(
    `By impact: critical=${byImpact.critical} serious=${byImpact.serious} `
    + `moderate=${byImpact.moderate} minor=${byImpact.minor}`,
  );
  console.log(`Full report: ${reportPath}`);

  for (const r of allResults) {
    if (r.violations.length === 0) continue;
    console.log(`\n${r.label}  (${r.url})`);
    for (const v of r.violations) {
      console.log(`  [${v.impact}] ${v.id}: ${v.help} (${v.nodes.length} node(s)) -- ${v.helpUrl}`);
    }
  }

  process.exitCode = totalViolations > 0 ? 1 : 0;
}

main();
