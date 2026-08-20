/**
 * Repo Seek — Scan for similar repositories, drill into a result as its
 * own seed (bounded to 3 item-scans per batch, 2 rounds deep), exclude
 * unwanted matches permanently, or bookmark one as a citation.
 */
(function () {
  'use strict';

  const SCAN_ENDPOINT = '/api/reposeek/scan';
  const MAX_DEPTH = 2;
  const MAX_ITEM_SCANS_PER_BATCH = 3;

  /** Current batch being viewed: {batch_id, depth, parent_batch_id, source_item, item_scans_used, repos}. */
  let currentBatch = null;
  /** Breadcrumb trail from the initial scan down to the current batch: [{label, batchId}]. batchId is null for the project root (not clickable -- re-scan via the Scan button instead). */
  let breadcrumbTrail = [];
  /** The row data behind whichever "Add Citation" click opened the modal. */
  let pendingCitationItem = null;

  /** Escape HTML to prevent XSS when rendering user-supplied strings. */
  function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = String(str);
    return div.innerHTML;
  }

  /** Format a number with locale separators (e.g. 1234 → "1,234"). */
  function formatNumber(n) {
    if (n == null) return '—';
    return Number(n).toLocaleString();
  }

  function getProject() {
    return (typeof state !== 'undefined' && state.currentProject) || (typeof currentProject !== 'undefined' && currentProject) || null;
  }

  /** Render a single match-reason tag. */
  function renderReason(reason) {
    return `<span class="inline-block bg-accent-sky/10 text-accent-sky border border-accent-sky/20 px-2 py-0.5 rounded font-code-sm text-code-sm">${escapeHtml(reason)}</span>`;
  }

  /** Render the lineage breadcrumb strip above the results table. */
  function renderLineage() {
    const el = document.getElementById('rs-lineage');
    if (!el) return;
    if (breadcrumbTrail.length <= 1) {
      el.classList.add('hidden');
      el.innerHTML = '';
      return;
    }
    el.classList.remove('hidden');
    el.innerHTML = breadcrumbTrail.map((crumb, i) => {
      const isLast = i === breadcrumbTrail.length - 1;
      const arrow = i > 0 ? '<span class="text-outline/50">→</span>' : '';
      const label = escapeHtml(crumb.label);
      if (isLast || !crumb.batchId) {
        return `${arrow}<span class="${isLast ? 'text-accent-lavender' : ''}">${label}</span>`;
      }
      return `${arrow}<button class="rs-breadcrumb-btn hover:underline hover:text-accent-lavender transition-colors cursor-pointer" data-batch-id="${escapeHtml(crumb.batchId)}">${label}</button>`;
    }).join(' ');
  }

  /** Render the full results table from a batch response. */
  function renderResults(batch) {
    const tbody = document.getElementById('rs-results-body');
    const wrapper = document.getElementById('rs-results-wrapper');
    const empty = document.getElementById('rs-empty');
    const exportControls = document.getElementById('rs-export-controls');
    if (!tbody || !wrapper) return;

    const repos = batch.repos || [];
    if (exportControls) exportControls.classList.remove('hidden');

    if (!Array.isArray(repos) || repos.length === 0) {
      wrapper.classList.add('hidden');
      if (empty) {
        empty.classList.remove('hidden');
        empty.innerHTML = batch.depth > 0
          ? '<p class="text-on-surface-variant font-body-sm">No new matches — everything found here was already excluded or already in the batch this was derived from. This branch stops here.</p>'
          : '<p class="text-on-surface-variant font-body-sm">No similar repositories found.</p>';
      }
      return;
    }

    if (empty) empty.classList.add('hidden');
    wrapper.classList.remove('hidden');

    // The 3-per-batch cap applies to the whole batch, not per-row -- once
    // hit (or once this batch is already the terminal depth-2 round),
    // every row's Scan Item action is disabled uniformly.
    const scanItemBlocked = batch.depth >= MAX_DEPTH || (batch.item_scans_used || 0) >= MAX_ITEM_SCANS_PER_BATCH;

    tbody.innerHTML = repos.map((repo) => {
      const title = escapeHtml(repo.title || repo.name || repo.full_name || 'Untitled');
      const url = repo.url || repo.html_url || repo.repo_url || '#';
      const safeUrl = escapeHtml(url);
      const language = escapeHtml(repo.language || repo.lang || '—');
      const stars = formatNumber(repo.stars ?? repo.stargazers_count ?? repo.score_stars);
      const score = repo.similarity_score != null ? Number(repo.similarity_score).toFixed(2) : (repo.score != null ? Number(repo.score).toFixed(1) : '—');
      const reasons = repo.match_reasons || repo.reasons || [];
      const reasonsHtml = Array.isArray(reasons) && reasons.length > 0
        ? reasons.map(renderReason).join(' ')
        : '<span class="text-outline">—</span>';
      const description = repo.description || '';

      return `<tr class="border-b border-glass-border hover:bg-surface-container/30 transition-colors" data-url="${safeUrl}">
        <td class="py-3 px-3 md:px-4">
          <a href="${safeUrl}" target="_blank" rel="noopener noreferrer"
             class="text-accent-lavender hover:underline font-body-sm break-all">${title}</a>
        </td>
        <td class="py-3 px-3 md:px-4 font-code-sm text-on-surface-variant whitespace-nowrap">${language}</td>
        <td class="py-3 px-3 md:px-4 font-code-sm text-on-surface-variant text-right whitespace-nowrap">${stars}</td>
        <td class="py-3 px-3 md:px-4 font-code-sm text-accent-lime text-right whitespace-nowrap">${score}</td>
        <td class="py-3 px-3 md:px-4">
          <div class="flex flex-wrap gap-1">${reasonsHtml}</div>
        </td>
        <td class="py-3 px-3 md:px-4">
          <div class="flex items-center gap-1.5 flex-wrap">
            <button class="rs-cite-btn px-2 py-1 rounded border border-glass-border text-outline font-code-sm hover:bg-surface-raised transition-all cursor-pointer"
                    data-title="${escapeHtml(title)}" data-url="${safeUrl}" data-description="${escapeHtml(description)}">Add Citation</button>
            <button class="rs-exclude-btn px-2 py-1 rounded border border-red-400/30 text-red-400 font-code-sm hover:bg-red-400/10 transition-all cursor-pointer"
                    data-title="${escapeHtml(title)}" data-url="${safeUrl}">Exclude</button>
            ${scanItemBlocked ? '' : `<button class="rs-scan-item-btn px-2 py-1 rounded border border-accent-lavender/30 text-accent-lavender font-code-sm hover:bg-accent-lavender/10 transition-all cursor-pointer" data-title="${escapeHtml(title)}" data-url="${safeUrl}">Scan Item</button>`}
          </div>
        </td>
      </tr>`;
    }).join('');
  }

  /** Render an error message in the error area. */
  function renderError(message) {
    const el = document.getElementById('rs-error');
    const empty = document.getElementById('rs-empty');
    const wrapper = document.getElementById('rs-results-wrapper');
    if (!el) return;

    if (wrapper) wrapper.classList.add('hidden');
    if (empty) empty.classList.add('hidden');

    el.classList.remove('hidden');
    el.innerHTML = `<div class="flex items-center gap-2 text-error bg-error-container/10 border border-error/30 rounded p-3">
      <span class="material-symbols-outlined text-[18px]">error</span>
      <span class="font-body-sm">${escapeHtml(message)}</span>
    </div>`;
  }

  /** Clear all result/error/empty states. */
  function clearState() {
    const error = document.getElementById('rs-error');
    const empty = document.getElementById('rs-empty');
    const wrapper = document.getElementById('rs-results-wrapper');
    const tbody = document.getElementById('rs-results-body');

    if (error) { error.classList.add('hidden'); error.innerHTML = ''; }
    if (empty) { empty.classList.add('hidden'); empty.innerHTML = ''; }
    if (wrapper) wrapper.classList.add('hidden');
    if (tbody) tbody.innerHTML = '';
  }

  /** Set loading state — spinner visible, button disabled, scan line active. */
  function setLoading(loading) {
    const btn = document.getElementById('rs-scan-btn');
    const spinner = document.getElementById('rs-spinner');
    const btnText = document.getElementById('rs-btn-text');

    if (btn) {
      btn.disabled = loading;
      btn.classList.toggle('scanning', loading);
    }
    if (spinner) spinner.classList.toggle('hidden', !loading);
    if (btnText) btnText.classList.toggle('hidden', loading);
  }

  function apiErrorMessage(res, detail) {
    if (res.status === 404) return 'Repo Seek endpoint not found. The feature may not be enabled yet.';
    if (res.status === 409) return detail || `Request blocked (${res.status})`;
    if (res.status === 429) return `Rate limited: ${detail}`;
    if (res.status >= 500) return `Server error: ${detail}`;
    return `Request failed (${res.status}): ${detail}`;
  }

  async function extractErrorDetail(res) {
    let detail = `Server returned ${res.status}`;
    try {
      const body = await res.json();
      detail = body.detail || body.error || detail;
    } catch (_) { /* non-JSON body */ }
    return detail;
  }

  /** Main scan handler — the initial, project-level scan. */
  async function runScan() {
    const project = getProject();

    if (!project) {
      renderError('No project selected. Select a project in the Memory tab first.');
      return;
    }

    clearState();
    setLoading(true);

    try {
      const url = `${SCAN_ENDPOINT}?project=${encodeURIComponent(project)}`;
      const res = await fetch(url);

      if (!res.ok) {
        const detail = await extractErrorDetail(res);
        if (res.status === 503) {
          renderError(`Rate limited: ${detail}`);
        } else {
          renderError(apiErrorMessage(res, detail));
        }
        return;
      }

      const data = await res.json();
      currentBatch = data;
      breadcrumbTrail = [{ label: project, batchId: null }];
      renderLineage();
      renderResults(data);
    } catch (err) {
      renderError(`Network error: ${err.message || 'Could not reach the server.'}`);
    } finally {
      setLoading(false);
    }
  }

  /** "Scan Item" — profile one result as its own project, search from it, replace the view with the new (child) batch. */
  async function scanItem(itemUrl, itemTitle) {
    const project = getProject();
    if (!project || !currentBatch) return;

    clearState();
    setLoading(true);

    try {
      const res = await fetch(`/api/reposeek/${encodeURIComponent(project)}/batches/${encodeURIComponent(currentBatch.batch_id)}/items/scan`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ item_url: itemUrl }),
      });

      if (!res.ok) {
        const detail = await extractErrorDetail(res);
        renderError(apiErrorMessage(res, detail));
        return;
      }

      const data = await res.json();
      currentBatch = data;
      breadcrumbTrail.push({ label: itemTitle, batchId: data.batch_id });
      renderLineage();
      renderResults(data);
    } catch (err) {
      renderError(`Network error: ${err.message || 'Could not reach the server.'}`);
    } finally {
      setLoading(false);
    }
  }

  /** Click a breadcrumb segment — reload a historical batch without re-scanning. */
  async function loadBatch(batchId) {
    const project = getProject();
    if (!project) return;

    clearState();
    setLoading(true);

    try {
      const res = await fetch(`/api/reposeek/${encodeURIComponent(project)}/batches/${encodeURIComponent(batchId)}`);
      if (!res.ok) {
        const detail = await extractErrorDetail(res);
        renderError(apiErrorMessage(res, detail));
        return;
      }
      const batch = await res.json();
      currentBatch = { ...batch, repos: batch.results };
      // Trim the trail back to (and including) the clicked crumb.
      const idx = breadcrumbTrail.findIndex((c) => c.batchId === batchId);
      if (idx !== -1) breadcrumbTrail = breadcrumbTrail.slice(0, idx + 1);
      renderLineage();
      renderResults(currentBatch);
    } catch (err) {
      renderError(`Network error: ${err.message || 'Could not reach the server.'}`);
    } finally {
      setLoading(false);
    }
  }

  /** "Exclude" — permanently hide this repo from future scans, remove its row now. */
  async function excludeItem(url, title, rowEl) {
    const project = getProject();
    if (!project) return;

    try {
      const res = await fetch(`/api/reposeek/${encodeURIComponent(project)}/exclude`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url, title }),
      });
      if (!res.ok) {
        const detail = await extractErrorDetail(res);
        if (typeof showToast === 'function') showToast(`Exclude failed: ${detail}`);
        return;
      }
      if (rowEl) rowEl.remove();
      if (currentBatch && Array.isArray(currentBatch.repos)) {
        currentBatch.repos = currentBatch.repos.filter((r) => (r.url || r.html_url) !== url);
      }
      if (typeof showToast === 'function') showToast('Excluded — won\'t appear in future scans.');
    } catch (err) {
      if (typeof showToast === 'function') showToast(`Network error: ${err.message}`);
    }
  }

  // ── Add Citation modal ──────────────────────────────────────────────

  function openCitationModal(title, url, description) {
    pendingCitationItem = { title, url, description };
    const modal = document.getElementById('rs-citation-modal');
    const titleEl = document.getElementById('rs-citation-title');
    const urlEl = document.getElementById('rs-citation-url');
    const summaryEl = document.getElementById('rs-citation-summary');
    if (titleEl) titleEl.value = title || '';
    if (urlEl) urlEl.value = url || '';
    if (summaryEl) summaryEl.value = description || '';
    if (modal) { modal.classList.remove('hidden'); modal.classList.add('flex'); }
  }

  function closeCitationModal() {
    pendingCitationItem = null;
    const modal = document.getElementById('rs-citation-modal');
    if (modal) { modal.classList.add('hidden'); modal.classList.remove('flex'); }
  }

  async function submitCitation() {
    const title = (document.getElementById('rs-citation-title')?.value || '').trim();
    const url = (document.getElementById('rs-citation-url')?.value || '').trim();
    const summary = (document.getElementById('rs-citation-summary')?.value || '').trim();
    if (!title || !url) {
      if (typeof showToast === 'function') showToast('Title and URL are required');
      return;
    }
    try {
      const res = await fetch('/api/citations', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title, url, summary, source: 'reposeek', tags: ['reposeek'] }),
      });
      if (!res.ok) {
        const detail = await extractErrorDetail(res);
        if (typeof showToast === 'function') showToast(`Citation failed: ${detail}`);
        return;
      }
      if (typeof showToast === 'function') showToast('Citation added');
      closeCitationModal();
      // Row deliberately stays in results -- Add Citation doesn't remove it.
    } catch (err) {
      if (typeof showToast === 'function') showToast(`Network error: ${err.message}`);
    }
  }

  // ── Export ───────────────────────────────────────────────────────────

  function copyToClipboard(text, successMessage) {
    navigator.clipboard.writeText(text).then(() => {
      if (typeof showToast === 'function') showToast(successMessage);
    }).catch((err) => {
      if (typeof showToast === 'function') showToast(`Copy failed: ${err.message}`);
    });
  }

  function copyCurrentBatchAsJson() {
    if (!currentBatch) return;
    copyToClipboard(JSON.stringify(currentBatch, null, 2), 'Copied batch as JSON');
  }

  function copyCurrentBatchAsMarkdown() {
    if (!currentBatch) return;
    const repos = currentBatch.repos || [];
    const lines = [`# Repo Seek — ${getProject() || ''}`, ''];
    if (currentBatch.source_item) {
      lines.push(`Derived from: ${currentBatch.source_item.title} (round ${currentBatch.depth})`);
    } else {
      lines.push('Initial scan');
    }
    lines.push('');
    if (!repos.length) {
      lines.push('_No results._');
    }
    repos.forEach((r) => {
      lines.push(`- [${r.title}](${r.url}) — ${r.language || 'unknown'}, ${r.stars || 0} stars, score ${(r.similarity_score ?? 0).toFixed(2)}`);
    });
    copyToClipboard(lines.join('\n'), 'Copied batch as Markdown');
  }

  async function exportAll() {
    const project = getProject();
    if (!project) return;
    try {
      const res = await fetch(`/api/reposeek/${encodeURIComponent(project)}/export?format=markdown`);
      if (!res.ok) {
        const detail = await extractErrorDetail(res);
        if (typeof showToast === 'function') showToast(`Export failed: ${detail}`);
        return;
      }
      const text = await res.text();
      const blob = new Blob([text], { type: 'text/markdown' });
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = `reposeek-${project}.md`;
      document.body.appendChild(a);
      a.click();
      a.remove();
    } catch (err) {
      if (typeof showToast === 'function') showToast(`Network error: ${err.message}`);
    }
  }

  // ── Event wiring ─────────────────────────────────────────────────────

  function init() {
    const scanBtn = document.getElementById('rs-scan-btn');
    if (scanBtn) scanBtn.addEventListener('click', runScan);

    const lineageEl = document.getElementById('rs-lineage');
    if (lineageEl) {
      lineageEl.addEventListener('click', (e) => {
        const btn = e.target.closest('.rs-breadcrumb-btn');
        if (btn) loadBatch(btn.dataset.batchId);
      });
    }

    const tbody = document.getElementById('rs-results-body');
    if (tbody) {
      tbody.addEventListener('click', (e) => {
        const citeBtn = e.target.closest('.rs-cite-btn');
        if (citeBtn) {
          openCitationModal(citeBtn.dataset.title, citeBtn.dataset.url, citeBtn.dataset.description);
          return;
        }
        const excludeBtn = e.target.closest('.rs-exclude-btn');
        if (excludeBtn) {
          const row = excludeBtn.closest('tr');
          excludeItem(excludeBtn.dataset.url, excludeBtn.dataset.title, row);
          return;
        }
        const scanItemBtn = e.target.closest('.rs-scan-item-btn');
        if (scanItemBtn) {
          scanItem(scanItemBtn.dataset.url, scanItemBtn.dataset.title);
        }
      });
    }

    const cancelBtn = document.getElementById('rs-citation-cancel-btn');
    if (cancelBtn) cancelBtn.addEventListener('click', closeCitationModal);
    const submitBtn = document.getElementById('rs-citation-submit-btn');
    if (submitBtn) submitBtn.addEventListener('click', submitCitation);
    const modal = document.getElementById('rs-citation-modal');
    if (modal) {
      modal.addEventListener('click', (e) => {
        if (e.target === modal) closeCitationModal(); // click on the backdrop
      });
    }

    const copyJsonBtn = document.getElementById('rs-copy-json-btn');
    if (copyJsonBtn) copyJsonBtn.addEventListener('click', copyCurrentBatchAsJson);
    const copyMdBtn = document.getElementById('rs-copy-md-btn');
    if (copyMdBtn) copyMdBtn.addEventListener('click', copyCurrentBatchAsMarkdown);
    const exportAllBtn = document.getElementById('rs-export-all-btn');
    if (exportAllBtn) exportAllBtn.addEventListener('click', exportAll);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
