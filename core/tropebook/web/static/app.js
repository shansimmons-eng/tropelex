const API_BASE = '/api';
let currentView = 'citations';
let selectedCitation = null;

document.addEventListener('DOMContentLoaded', () => {
    initNavigation();
    initSearch();
    initForms();
    initModal();
    loadCitations();
    loadStats();
});

function initNavigation() {
    document.querySelectorAll('.nav-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const view = btn.dataset.view;
            showView(view);
        });
    });
}

function showView(view) {
    document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
    document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
    document.getElementById(`${view}-view`).classList.add('active');
    document.querySelector(`[data-view="${view}"]`).classList.add('active');
    currentView = view;
}

function initSearch() {
    const searchBtn = document.getElementById('search-btn');
    const searchInput = document.getElementById('search-input');
    
    searchBtn?.addEventListener('click', () => searchCitations(searchInput.value));
    searchInput?.addEventListener('keypress', e => {
        if (e.key === 'Enter') searchCitations(searchInput.value);
    });
    
    const researchBtn = document.getElementById('research-btn');
    const researchInput = document.getElementById('research-input');
    
    researchBtn?.addEventListener('click', () => runResearch(researchInput.value));
    researchInput?.addEventListener('keypress', e => {
        if (e.key === 'Enter') runResearch(researchInput.value);
    });
}

function initForms() {
    document.getElementById('add-form')?.addEventListener('submit', async e => {
        e.preventDefault();
        const title = document.getElementById('add-title').value;
        const url = document.getElementById('add-url').value;
        const summary = document.getElementById('add-summary').value;
        const tags = document.getElementById('add-tags').value.split(',').map(t => t.trim()).filter(Boolean);
        
        try {
            const res = await fetch(`${API_BASE}/citations`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({title, url, summary, tags})
            });
            if (res.ok) {
                alert('Citation added!');
                e.target.reset();
                showView('citations');
                loadCitations();
            }
        } catch (err) {
            console.error(err);
        }
    });
}

function initModal() {
    const modal = document.getElementById('citation-modal');
    const closeBtn = modal?.querySelector('.close');
    
    closeBtn?.addEventListener('click', () => modal.style.display = 'none');
    window.addEventListener('click', e => {
        if (e.target === modal) modal.style.display = 'none';
    });
    
    document.getElementById('modal-delete')?.addEventListener('click', async () => {
        if (!selectedCitation) return;
        if (!confirm('Delete this citation?')) return;
        
        await fetch(`${API_BASE}/citations/${selectedCitation}`, {method: 'DELETE'});
        modal.style.display = 'none';
        loadCitations();
        loadStats();
    });
}

async function loadCitations(tag = null, source = null) {
    const container = document.getElementById('citations-list');
    container.innerHTML = '<div class="loading">Loading...</div>';
    
    try {
        const url = new URL(`${API_BASE}/citations`, window.location.origin);
        if (tag) url.searchParams.set('tag', tag);
        if (source) url.searchParams.set('source', source);
        
        const res = await fetch(url);
        const data = await res.json();
        
        if (data.citations.length === 0) {
            container.innerHTML = '<p>No citations found.</p>';
            return;
        }
        
        container.innerHTML = data.citations.map(c => `
            <div class="citation-card" data-cid="${c.url}">
                <h3>${escapeHtml(c.title)}</h3>
                <a href="${escapeHtml(c.url)}" target="_blank">${escapeHtml(c.url)}</a>
                ${c.summary ? `<p>${escapeHtml(c.summary)}</p>` : ''}
                ${c.tags && c.tags.length ? `
                    <div class="tags">
                        ${c.tags.map(t => `<span class="tag">${escapeHtml(t)}</span>`).join('')}
                    </div>
                ` : ''}
            </div>
        `).join('');
        
        container.querySelectorAll('.citation-card').forEach(card => {
            card.addEventListener('click', () => showCitationDetail(card.dataset.cid));
        });
        
        document.getElementById('citation-count').textContent = data.count;
        updateFilters(data.citations);
    } catch (err) {
        container.innerHTML = `<div class="error">Error loading citations: ${err.message}</div>`;
    }
}

async function searchCitations(query) {
    if (!query.trim()) return;
    
    const container = document.getElementById('citations-list');
    container.innerHTML = '<div class="loading">Searching...</div>';
    
    try {
        const res = await fetch(`${API_BASE}/search?q=${encodeURIComponent(query)}`);
        const data = await res.json();
        
        if (data.results.length === 0) {
            container.innerHTML = '<p>No results found.</p>';
            return;
        }
        
        container.innerHTML = data.results.map(c => `
            <div class="citation-card" data-cid="${c.url}">
                <h3>${escapeHtml(c.title)}</h3>
                <a href="${escapeHtml(c.url)}" target="_blank">${escapeHtml(c.url)}</a>
                ${c.summary ? `<p>${escapeHtml(c.summary)}</p>` : ''}
            </div>
        `).join('');
    } catch (err) {
        container.innerHTML = `<div class="error">Search error: ${err.message}</div>`;
    }
}

async function runResearch(query) {
    if (!query.trim()) return;
    
    const container = document.getElementById('research-results');
    container.innerHTML = '<div class="loading">Researching...</div>';
    
    try {
        const res = await fetch(`${API_BASE}/research?query=${encodeURIComponent(query)}`);
        const data = await res.json();
        
        if (data.results.length === 0) {
            container.innerHTML = '<p>No results found.</p>';
            return;
        }
        
        container.innerHTML = data.results.map(r => `
            <div class="citation-card">
                <h3>${escapeHtml(r.title)}</h3>
                <a href="${escapeHtml(r.url)}" target="_blank">${escapeHtml(r.url)}</a>
                ${r.description ? `<p>${escapeHtml(r.description)}</p>` : ''}
                <button onclick="addResearchResult('${escapeHtml(r.url)}', '${escapeHtml(r.title)}')">
                    Save to Tropebook
                </button>
            </div>
        `).join('');
    } catch (err) {
        container.innerHTML = `<div class="error">Research error: ${err.message}</div>`;
    }
}

async function addResearchResult(url, title) {
    try {
        await fetch(`${API_BASE}/citations`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({title, url, source: 'research'})
        });
        alert('Added to Tropebook!');
    } catch (err) {
        alert('Error adding citation');
    }
}

async function showCitationDetail(url) {
    const modal = document.getElementById('citation-modal');
    
    try {
        const res = await fetch(`${API_BASE}/citations`);
        const data = await res.json();
        const citation = data.citations.find(c => c.url === url);
        
        if (!citation) return;
        
        selectedCitation = citation.url;
        document.getElementById('modal-title').textContent = citation.title;
        document.getElementById('modal-url').href = citation.url;
        document.getElementById('modal-url').textContent = citation.url;
        document.getElementById('modal-summary').textContent = citation.summary || 'No summary';
        
        const tagsContainer = document.getElementById('modal-tags');
        tagsContainer.innerHTML = citation.tags?.map(t => `<span class="tag">${escapeHtml(t)}</span>`).join('') || '';
        
        modal.style.display = 'block';
    } catch (err) {
        console.error(err);
    }
}

async function loadStats() {
    try {
        const res = await fetch(`${API_BASE}/stats`);
        const stats = await res.json();
        document.getElementById('stats-content').innerHTML = `
            <p>Total Citations: ${stats.total_citations}</p>
            <p>Total Relationships: ${stats.total_relationships}</p>
            <p>Total Tags: ${stats.total_tags}</p>
        `;
    } catch (err) {
        console.error(err);
    }
}

function updateFilters(citations) {
    const tagFilter = document.getElementById('tag-filter');
    const sourceFilter = document.getElementById('source-filter');
    
    const tags = [...new Set(citations.flatMap(c => c.tags || []))];
    const sources = [...new Set(citations.map(c => c.source_type).filter(Boolean))];
    
    tagFilter.innerHTML = '<option value="">All Tags</option>' + 
        tags.map(t => `<option value="${escapeHtml(t)}">${escapeHtml(t)}</option>`).join('');
    sourceFilter.innerHTML = '<option value="">All Sources</option>' + 
        sources.map(s => `<option value="${escapeHtml(s)}">${escapeHtml(s)}</option>`).join('');
    
    tagFilter.addEventListener('change', () => loadCitations(tagFilter.value, sourceFilter.value));
    sourceFilter.addEventListener('change', () => loadCitations(tagFilter.value, sourceFilter.value));
}

function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}