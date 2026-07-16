const API_BASE = '/api';
let currentView = 'tropebook-view';

document.addEventListener('DOMContentLoaded', () => {
    loadCitations();
    loadStats();
});

async function loadCitations(tag = null, source = null) {
    const container = document.getElementById('citations-list');
    if (!container) return;
    
    container.innerHTML = '<div class="p-4 text-outline">Loading...</div>';
    
    try {
        const url = new URL(`${API_BASE}/citations`, window.location.origin);
        if (tag) url.searchParams.set('tag', tag);
        if (source) url.searchParams.set('source', source);
        
        const res = await fetch(url);
        const data = await res.json();
        
        if (data.citations.length === 0) {
            container.innerHTML = '<div class="glass-panel p-4 text-on-surface-variant">No citations found. Use the search to add research.</div>';
            return;
        }
        
        container.innerHTML = data.citations.map(c => `
            <article class="glass-panel rounded p-4 flex flex-col gap-3 hover:bg-surface-container/50 transition-colors">
                <div class="flex justify-between items-start">
                    <div class="flex gap-2 items-center">
                        <div class="bg-accent-lavender/10 text-accent-lavender border border-accent-lavender/30 px-2 py-0.5 rounded font-label-caps text-label-caps flex items-center gap-1">
                            <span class="material-symbols-outlined text-[12px]">description</span>
                            ${c.source_type?.toUpperCase() || 'MANUAL'}
                        </div>
                    </div>
                    <div class="flex gap-2">
                        <span class="material-symbols-outlined text-outline hover:text-accent-lavender cursor-pointer text-[18px] transition-colors" data-icon="bookmark_add">bookmark_add</span>
                    </div>
                </div>
                <h3 class="font-headline-md text-headline-md text-on-surface leading-tight">${escapeHtml(c.title)}</h3>
                ${c.summary ? `<p class="font-body-sm text-body-sm text-on-surface-variant line-clamp-2">${escapeHtml(c.summary)}</p>` : ''}
                ${c.tags && c.tags.length ? `
                    <div class="flex flex-wrap gap-2 mt-1">
                        ${c.tags.map(t => `<span class="bg-accent-sky/10 text-accent-sky border border-accent-sky/20 px-2 py-1 rounded font-code-sm text-code-sm">${escapeHtml(t)}</span>`).join('')}
                    </div>
                ` : ''}
                <div class="border-t border-glass-border pt-3 mt-1 flex items-center gap-2 text-outline font-code-sm text-code-sm">
                    <span class="material-symbols-outlined text-[14px]" data-icon="link">link</span>
                    <a class="hover:text-accent-lavender truncate transition-colors" href="${escapeHtml(c.url)}" target="_blank">${escapeHtml(c.url)}</a>
                </div>
            </article>
        `).join('');
        
        document.getElementById('citation-count').textContent = `INDEX: ${data.count} ENTITIES FOUND`;
    } catch (err) {
        container.innerHTML = `<div class="glass-panel p-4 text-error">Error loading citations: ${err.message}</div>`;
    }
}

async function searchCitations(query) {
    if (!query.trim()) return;
    
    const container = document.getElementById('citations-list');
    container.innerHTML = '<div class="p-4 text-outline">Searching...</div>';
    
    try {
        const res = await fetch(`${API_BASE}/search?q=${encodeURIComponent(query)}`);
        const data = await res.json();
        
        if (data.results.length === 0) {
            container.innerHTML = '<div class="glass-panel p-4 text-on-surface-variant">No results found.</div>';
            return;
        }
        
        container.innerHTML = data.results.map(c => `
            <article class="glass-panel rounded p-4 flex flex-col gap-3 hover:bg-surface-container/50 transition-colors">
                <h3 class="font-headline-md text-headline-md text-on-surface leading-tight">${escapeHtml(c.title)}</h3>
                ${c.summary ? `<p class="font-body-sm text-body-sm text-on-surface-variant">${escapeHtml(c.summary)}</p>` : ''}
                <div class="flex items-center gap-2 text-outline font-code-sm">
                    <span class="material-symbols-outlined text-[14px]">link</span>
                    <a href="${escapeHtml(c.url)}" target="_blank">${escapeHtml(c.url)}</a>
                </div>
            </article>
        `).join('');
        
        document.getElementById('citation-count').textContent = `FOUND: ${data.count} RESULTS`;
    } catch (err) {
        container.innerHTML = `<div class="text-error">Search error: ${err.message}</div>`;
    }
}

document.getElementById('tb-search-btn')?.addEventListener('click', () => {
    const input = document.getElementById('tb-search-input');
    searchCitations(input.value);
});

document.getElementById('tb-search-input')?.addEventListener('keypress', e => {
    if (e.key === 'Enter') {
        searchCitations(e.target.value);
    }
});

async function loadStats() {
    try {
        const res = await fetch(`${API_BASE}/stats`);
        const stats = await res.json();
        const status = document.getElementById('tb-status');
        if (status) {
            status.textContent = stats.total_citations > 0 ? 'ACTIVE' : 'IDLE';
        }
    } catch (err) {
        console.error(err);
    }
}

function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}