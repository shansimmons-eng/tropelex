/**
 * Repo Seek — Scan for similar repositories.
 * Handles button click, loading state, results rendering, and error display.
 */
(function () {
  'use strict';

  const SCAN_ENDPOINT = '/api/reposeek/scan';

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

  /** Render a single match-reason tag. */
  function renderReason(reason) {
    return `<span class="inline-block bg-accent-sky/10 text-accent-sky border border-accent-sky/20 px-2 py-0.5 rounded font-code-sm text-code-sm">${escapeHtml(reason)}</span>`;
  }

  /** Render the full results table from API response data. */
  function renderResults(data) {
    const tbody = document.getElementById('rs-results-body');
    const wrapper = document.getElementById('rs-results-wrapper');
    const empty = document.getElementById('rs-empty');
    if (!tbody || !wrapper) return;

    const repos = data.repos || data.results || data;

    if (!Array.isArray(repos) || repos.length === 0) {
      wrapper.classList.add('hidden');
      if (empty) {
        empty.classList.remove('hidden');
        empty.innerHTML = '<p class="text-on-surface-variant font-body-sm">No similar repositories found.</p>';
      }
      return;
    }

    if (empty) empty.classList.add('hidden');
    wrapper.classList.remove('hidden');

    tbody.innerHTML = repos.map((repo) => {
      const title = escapeHtml(repo.title || repo.name || repo.full_name || 'Untitled');
      const url = escapeHtml(repo.url || repo.html_url || repo.repo_url || '#');
      const language = escapeHtml(repo.language || repo.lang || '—');
      const stars = formatNumber(repo.stars ?? repo.stargazers_count ?? repo.score_stars);
      const score = repo.score != null ? Number(repo.score).toFixed(1) : '—';
      const reasons = repo.match_reasons || repo.reasons || [];
      const reasonsHtml = Array.isArray(reasons) && reasons.length > 0
        ? reasons.map(renderReason).join(' ')
        : '<span class="text-outline">—</span>';

      return `<tr class="border-b border-glass-border hover:bg-surface-container/30 transition-colors">
        <td class="py-3 px-3 md:px-4">
          <a href="${url}" target="_blank" rel="noopener noreferrer"
             class="text-accent-lavender hover:underline font-body-sm break-all">${title}</a>
        </td>
        <td class="py-3 px-3 md:px-4 font-code-sm text-on-surface-variant whitespace-nowrap">${language}</td>
        <td class="py-3 px-3 md:px-4 font-code-sm text-on-surface-variant text-right whitespace-nowrap">${stars}</td>
        <td class="py-3 px-3 md:px-4 font-code-sm text-accent-lime text-right whitespace-nowrap">${score}</td>
        <td class="py-3 px-3 md:px-4">
          <div class="flex flex-wrap gap-1">${reasonsHtml}</div>
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

  /** Main scan handler. */
  async function runScan() {
    const project = (typeof state !== 'undefined' && state.currentProject) || (typeof currentProject !== 'undefined' && currentProject) || null;

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
        let detail = `Server returned ${res.status}`;
        try {
          const body = await res.json();
          detail = body.detail || body.error || detail;
        } catch (_) { /* non-JSON body */ }

        if (res.status === 404) {
          renderError('Repo Seek endpoint not found. The feature may not be enabled yet.');
        } else if (res.status === 429) {
          renderError(`Rate limited: ${detail}`);
        } else if (res.status >= 500) {
          renderError(`Server error: ${detail}`);
        } else {
          renderError(`Request failed (${res.status}): ${detail}`);
        }
        return;
      }

      const data = await res.json();
      renderResults(data);
    } catch (err) {
      renderError(`Network error: ${err.message || 'Could not reach the server.'}`);
    } finally {
      setLoading(false);
    }
  }

  /** Bind once DOM is ready. */
  function init() {
    const btn = document.getElementById('rs-scan-btn');
    if (btn) {
      btn.addEventListener('click', runScan);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
