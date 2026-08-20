/**
 * Trending — a proxy for github.com/trending (which has no public API):
 * recently-pushed repos sorted by stars, with real star deltas computed
 * against your own past scans of the same filter combination. Standalone
 * from Repo Seek: no batches, no depth/width caps, no project scoping --
 * this is global GitHub discovery, not a profile of one Tropelex project.
 */
(function () {
  'use strict';

  const SCAN_ENDPOINT = '/api/trending/scan';

  /** The last /scan response: {snapshot_id, window, language, topics, previous_snapshot_at, repos}. */
  let currentScan = null;

  function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = String(str);
    return div.innerHTML;
  }

  function formatNumber(n) {
    if (n == null) return '—';
    return Number(n).toLocaleString();
  }

  function formatDelta(delta, firstSeen) {
    if (firstSeen === true) {
      return '<span class="inline-block bg-accent-lime/10 text-accent-lime border border-accent-lime/20 px-2 py-0.5 rounded font-code-sm text-code-sm">NEW</span>';
    }
    if (delta == null) return '<span class="text-outline">—</span>';
    const sign = delta > 0 ? '+' : '';
    const cls = delta > 0 ? 'text-accent-lime' : (delta < 0 ? 'text-red-400' : 'text-outline');
    return `<span class="${cls} font-code-sm">${sign}${formatNumber(delta)}</span>`;
  }

  function formatDate(iso) {
    if (!iso) return '';
    try {
      return new Date(iso).toLocaleString();
    } catch (_) {
      return iso;
    }
  }

  function getFilters() {
    const language = (document.getElementById('trend-language-input')?.value || '').trim();
    const topics = (document.getElementById('trend-topics-input')?.value || '').trim();
    const window_ = document.getElementById('trend-window-select')?.value || 'week';
    return { language, topics, window: window_ };
  }

  function renderBaseline(data) {
    const el = document.getElementById('trend-baseline');
    if (!el) return;
    el.classList.remove('hidden');
    if (data.previous_snapshot_at) {
      el.textContent = `Deltas compared against the scan from ${formatDate(data.previous_snapshot_at)}.`;
    } else {
      el.textContent = 'First scan for this exact filter combination — no prior snapshot to compare against yet.';
    }
  }

  function renderResults(data) {
    const tbody = document.getElementById('trend-results-body');
    const wrapper = document.getElementById('trend-results-wrapper');
    const empty = document.getElementById('trend-empty');
    if (!tbody || !wrapper) return;

    const repos = data.repos || [];
    if (!Array.isArray(repos) || repos.length === 0) {
      wrapper.classList.add('hidden');
      if (empty) {
        empty.classList.remove('hidden');
        empty.innerHTML = '<p class="text-on-surface-variant font-body-sm">No repos matched this filter combination.</p>';
      }
      return;
    }

    if (empty) empty.classList.add('hidden');
    wrapper.classList.remove('hidden');

    tbody.innerHTML = repos.map((repo) => {
      const title = escapeHtml(repo.title || 'Untitled');
      const url = repo.url || '#';
      const safeUrl = escapeHtml(url);
      const language = escapeHtml(repo.language || '—');
      const stars = formatNumber(repo.stars);
      const delta = formatDelta(repo.delta_stars, repo.first_seen);
      const description = repo.description || '';
      const descShort = escapeHtml(description.length > 140 ? description.slice(0, 140) + '…' : description);

      return `<tr class="border-b border-glass-border hover:bg-surface-container/30 transition-colors" data-url="${safeUrl}">
        <td class="py-3 px-3 md:px-4">
          <a href="${safeUrl}" target="_blank" rel="noopener noreferrer"
             class="text-accent-lavender hover:underline font-body-sm break-all">${title}</a>
        </td>
        <td class="py-3 px-3 md:px-4 font-code-sm text-on-surface-variant whitespace-nowrap">${language}</td>
        <td class="py-3 px-3 md:px-4 font-code-sm text-on-surface-variant text-right whitespace-nowrap">${stars}</td>
        <td class="py-3 px-3 md:px-4 text-right whitespace-nowrap">${delta}</td>
        <td class="py-3 px-3 md:px-4 font-body-sm text-on-surface-variant">${descShort}</td>
        <td class="py-3 px-3 md:px-4">
          <div class="flex items-center gap-1.5 flex-wrap">
            <button class="trend-cite-btn px-2 py-1 rounded border border-glass-border text-outline font-code-sm hover:bg-surface-raised transition-all cursor-pointer"
                    data-title="${escapeHtml(title)}" data-url="${safeUrl}" data-description="${escapeHtml(description)}">Add Citation</button>
            <button class="trend-exclude-btn px-2 py-1 rounded border border-red-400/30 text-red-400 font-code-sm hover:bg-red-400/10 transition-all cursor-pointer"
                    data-title="${escapeHtml(title)}" data-url="${safeUrl}">Exclude</button>
            <button class="trend-similar-btn px-2 py-1 rounded border border-accent-lavender/30 text-accent-lavender font-code-sm hover:bg-accent-lavender/10 transition-all cursor-pointer"
                    data-title="${escapeHtml(title)}" data-url="${safeUrl}" data-description="${escapeHtml(description)}" data-language="${language === '—' ? '' : language}">Show Similar</button>
          </div>
        </td>
      </tr>`;
    }).join('');
  }

  function renderError(message) {
    const el = document.getElementById('trend-error');
    const empty = document.getElementById('trend-empty');
    const wrapper = document.getElementById('trend-results-wrapper');
    if (!el) return;

    if (wrapper) wrapper.classList.add('hidden');
    if (empty) empty.classList.add('hidden');

    el.classList.remove('hidden');
    el.innerHTML = `<div class="flex items-center gap-2 text-error bg-error-container/10 border border-error/30 rounded p-3">
      <span class="material-symbols-outlined text-[18px]">error</span>
      <span class="font-body-sm">${escapeHtml(message)}</span>
    </div>`;
  }

  function clearState() {
    const error = document.getElementById('trend-error');
    const empty = document.getElementById('trend-empty');
    const wrapper = document.getElementById('trend-results-wrapper');
    const tbody = document.getElementById('trend-results-body');
    const baseline = document.getElementById('trend-baseline');

    if (error) { error.classList.add('hidden'); error.innerHTML = ''; }
    if (empty) { empty.classList.add('hidden'); empty.innerHTML = ''; }
    if (wrapper) wrapper.classList.add('hidden');
    if (tbody) tbody.innerHTML = '';
    if (baseline) baseline.classList.add('hidden');
  }

  function setLoading(loading) {
    const btn = document.getElementById('trend-scan-btn');
    const spinner = document.getElementById('trend-spinner');
    const btnText = document.getElementById('trend-btn-text');

    if (btn) btn.disabled = loading;
    if (spinner) spinner.classList.toggle('hidden', !loading);
    if (btnText) btnText.classList.toggle('hidden', loading);
  }

  function apiErrorMessage(res, detail) {
    if (res.status === 404) return 'Trending endpoint not found. The feature may not be enabled yet.';
    if (res.status === 422) return detail || `Invalid request (${res.status})`;
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

  async function runScan() {
    const { language, topics, window: windowVal } = getFilters();

    clearState();
    setLoading(true);

    try {
      const params = new URLSearchParams({ window: windowVal });
      if (language) params.set('language', language);
      if (topics) params.set('topics', topics);

      const res = await fetch(`${SCAN_ENDPOINT}?${params.toString()}`);

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
      currentScan = data;
      renderBaseline(data);
      renderResults(data);
    } catch (err) {
      renderError(`Network error: ${err.message || 'Could not reach the server.'}`);
    } finally {
      setLoading(false);
    }
  }

  async function excludeItem(url, title, rowEl) {
    try {
      const res = await fetch('/api/trending/exclude', {
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
      if (currentScan && Array.isArray(currentScan.repos)) {
        currentScan.repos = currentScan.repos.filter((r) => r.url !== url);
      }
      if (typeof showToast === 'function') showToast('Excluded — won\'t appear in future scans.');
    } catch (err) {
      if (typeof showToast === 'function') showToast(`Network error: ${err.message}`);
    }
  }

  // ── Show Similar modal (one-shot, not persisted) ────────────────────

  async function openRelatedModal(title, url, description, language) {
    const modal = document.getElementById('trend-related-modal');
    const body = document.getElementById('trend-related-body');
    if (!modal || !body) return;

    body.innerHTML = '<p class="text-on-surface-variant font-body-sm">Searching…</p>';
    modal.classList.remove('hidden');
    modal.classList.add('flex');

    try {
      const res = await fetch('/api/trending/related', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title, url, description, language: language || null }),
      });
      if (!res.ok) {
        const detail = await extractErrorDetail(res);
        body.innerHTML = `<p class="text-error font-body-sm">${escapeHtml(apiErrorMessage(res, detail))}</p>`;
        return;
      }
      const data = await res.json();
      const repos = data.repos || [];
      if (!repos.length) {
        body.innerHTML = '<p class="text-on-surface-variant font-body-sm">No similar repos found.</p>';
        return;
      }
      body.innerHTML = repos.map((r) => {
        const safeUrl = escapeHtml(r.url);
        const rTitle = escapeHtml(r.title);
        return `<div class="flex items-center justify-between gap-2 border-b border-glass-border py-2">
          <div class="min-w-0">
            <a href="${safeUrl}" target="_blank" rel="noopener noreferrer" class="text-accent-lavender hover:underline font-body-sm break-all">${rTitle}</a>
            <div class="text-xs text-outline">${escapeHtml(r.language || '—')} · ${formatNumber(r.stars)} stars</div>
          </div>
          <button class="trend-related-cite-btn shrink-0 px-2 py-1 rounded border border-glass-border text-outline font-code-sm hover:bg-surface-raised transition-all cursor-pointer"
                  data-title="${rTitle}" data-url="${safeUrl}" data-description="${escapeHtml(r.description || '')}">Add Citation</button>
        </div>`;
      }).join('');
    } catch (err) {
      body.innerHTML = `<p class="text-error font-body-sm">Network error: ${escapeHtml(err.message || '')}</p>`;
    }
  }

  function closeRelatedModal() {
    const modal = document.getElementById('trend-related-modal');
    if (modal) { modal.classList.add('hidden'); modal.classList.remove('flex'); }
  }

  // ── History modal ────────────────────────────────────────────────────

  async function openHistoryModal() {
    const { language, topics, window: windowVal } = getFilters();
    const modal = document.getElementById('trend-history-modal');
    const body = document.getElementById('trend-history-body');
    if (!modal || !body) return;

    body.innerHTML = '<p class="text-on-surface-variant font-body-sm">Loading…</p>';
    modal.classList.remove('hidden');
    modal.classList.add('flex');

    try {
      const params = new URLSearchParams({ window: windowVal });
      if (language) params.set('language', language);
      if (topics) params.set('topics', topics);

      const res = await fetch(`/api/trending/history?${params.toString()}`);
      if (!res.ok) {
        const detail = await extractErrorDetail(res);
        body.innerHTML = `<p class="text-error font-body-sm">${escapeHtml(apiErrorMessage(res, detail))}</p>`;
        return;
      }
      const data = await res.json();
      const history = data.history || [];
      if (!history.length) {
        body.innerHTML = '<p class="text-on-surface-variant font-body-sm">No scans yet for this filter combination.</p>';
        return;
      }
      body.innerHTML = history.slice().reverse().map((h) => `
        <div class="flex items-center justify-between border-b border-glass-border py-2 font-code-sm">
          <span class="text-on-surface-variant">${escapeHtml(formatDate(h.created_at))}</span>
          <span class="text-outline">${h.result_count} repos</span>
        </div>
      `).join('');
    } catch (err) {
      body.innerHTML = `<p class="text-error font-body-sm">Network error: ${escapeHtml(err.message || '')}</p>`;
    }
  }

  function closeHistoryModal() {
    const modal = document.getElementById('trend-history-modal');
    if (modal) { modal.classList.add('hidden'); modal.classList.remove('flex'); }
  }

  // ── Add Citation modal ──────────────────────────────────────────────

  function openCitationModal(title, url, description) {
    const modal = document.getElementById('trend-citation-modal');
    const titleEl = document.getElementById('trend-citation-title');
    const urlEl = document.getElementById('trend-citation-url');
    const summaryEl = document.getElementById('trend-citation-summary');
    if (titleEl) titleEl.value = title || '';
    if (urlEl) urlEl.value = url || '';
    if (summaryEl) summaryEl.value = description || '';
    if (modal) { modal.classList.remove('hidden'); modal.classList.add('flex'); }
  }

  function closeCitationModal() {
    const modal = document.getElementById('trend-citation-modal');
    if (modal) { modal.classList.add('hidden'); modal.classList.remove('flex'); }
  }

  async function submitCitation() {
    const title = (document.getElementById('trend-citation-title')?.value || '').trim();
    const url = (document.getElementById('trend-citation-url')?.value || '').trim();
    const summary = (document.getElementById('trend-citation-summary')?.value || '').trim();
    if (!title || !url) {
      if (typeof showToast === 'function') showToast('Title and URL are required');
      return;
    }
    try {
      const res = await fetch('/api/citations', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title, url, summary, source: 'trending', tags: ['trending'] }),
      });
      if (!res.ok) {
        const detail = await extractErrorDetail(res);
        if (typeof showToast === 'function') showToast(`Citation failed: ${detail}`);
        return;
      }
      if (typeof showToast === 'function') showToast('Citation added');
      closeCitationModal();
    } catch (err) {
      if (typeof showToast === 'function') showToast(`Network error: ${err.message}`);
    }
  }

  // ── Event wiring ─────────────────────────────────────────────────────

  function init() {
    const scanBtn = document.getElementById('trend-scan-btn');
    if (scanBtn) scanBtn.addEventListener('click', runScan);

    const historyBtn = document.getElementById('trend-history-btn');
    if (historyBtn) historyBtn.addEventListener('click', openHistoryModal);
    const historyCloseBtn = document.getElementById('trend-history-close-btn');
    if (historyCloseBtn) historyCloseBtn.addEventListener('click', closeHistoryModal);
    const historyModal = document.getElementById('trend-history-modal');
    if (historyModal) {
      historyModal.addEventListener('click', (e) => {
        if (e.target === historyModal) closeHistoryModal();
      });
    }

    const tbody = document.getElementById('trend-results-body');
    if (tbody) {
      tbody.addEventListener('click', (e) => {
        const citeBtn = e.target.closest('.trend-cite-btn');
        if (citeBtn) {
          openCitationModal(citeBtn.dataset.title, citeBtn.dataset.url, citeBtn.dataset.description);
          return;
        }
        const excludeBtn = e.target.closest('.trend-exclude-btn');
        if (excludeBtn) {
          const row = excludeBtn.closest('tr');
          excludeItem(excludeBtn.dataset.url, excludeBtn.dataset.title, row);
          return;
        }
        const similarBtn = e.target.closest('.trend-similar-btn');
        if (similarBtn) {
          openRelatedModal(similarBtn.dataset.title, similarBtn.dataset.url, similarBtn.dataset.description, similarBtn.dataset.language);
        }
      });
    }

    const relatedBody = document.getElementById('trend-related-body');
    if (relatedBody) {
      relatedBody.addEventListener('click', (e) => {
        const citeBtn = e.target.closest('.trend-related-cite-btn');
        if (citeBtn) {
          closeRelatedModal();
          openCitationModal(citeBtn.dataset.title, citeBtn.dataset.url, citeBtn.dataset.description);
        }
      });
    }
    const relatedCloseBtn = document.getElementById('trend-related-close-btn');
    if (relatedCloseBtn) relatedCloseBtn.addEventListener('click', closeRelatedModal);
    const relatedModal = document.getElementById('trend-related-modal');
    if (relatedModal) {
      relatedModal.addEventListener('click', (e) => {
        if (e.target === relatedModal) closeRelatedModal();
      });
    }

    const cancelBtn = document.getElementById('trend-citation-cancel-btn');
    if (cancelBtn) cancelBtn.addEventListener('click', closeCitationModal);
    const submitBtn = document.getElementById('trend-citation-submit-btn');
    if (submitBtn) submitBtn.addEventListener('click', submitCitation);
    const citationModal = document.getElementById('trend-citation-modal');
    if (citationModal) {
      citationModal.addEventListener('click', (e) => {
        if (e.target === citationModal) closeCitationModal();
      });
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
