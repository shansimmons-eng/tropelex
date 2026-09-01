/**
 * Keyword-landing fallback for the dashboard's documentation search
 * widget. A real heading id (see scripts/anchor_guide_subsections.py)
 * gets a search result to the right *section* -- this refines further,
 * to the exact sentence a search actually matched on, when that text
 * lives partway down a section rather than right at its heading.
 *
 * Shared across all 4 site/*.html pages (and their locally-served
 * mirrors, core/tropebook/web/static/*.html, via scripts/sync_local_
 * docs.py) rather than duplicated per page -- identical logic
 * duplicated 4x is exactly the kind of silent-drift risk this project
 * already hit once with the site/<->static mirror staleness bug.
 */
(function () {
    "use strict";

    function getHighlightQuery() {
        return new URLSearchParams(window.location.search).get("hl");
    }

    function tokenize(text) {
        return (text.toLowerCase().match(/[a-z][a-z0-9]+/g) || []).filter((w) => w.length > 2);
    }

    // Same exclusions core/docs_search.py's _SectionParser applies when
    // building the index this query came from: skip script/style, and
    // skip Material Symbols icon spans (their text is a ligature-
    // rendered glyph name, not real page content -- matching against it
    // would land on an icon, not a sentence). Also skips the sidebar
    // "Table of contents" nav -- on the GUIDE specifically it lists every
    // section's title in DOM order *before* the actual content, so an
    // unqualified scan would match a nav label instead of the real prose
    // whenever a query word happened to also appear in some section's name.
    function collectTextNodes(root) {
        const nodes = [];
        const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
            acceptNode(node) {
                const parent = node.parentElement;
                if (!parent) return NodeFilter.FILTER_REJECT;
                const tag = parent.tagName;
                if (tag === "SCRIPT" || tag === "STYLE" || tag === "NOSCRIPT") {
                    return NodeFilter.FILTER_REJECT;
                }
                if (parent.classList && parent.classList.contains("material-symbols-outlined")) {
                    return NodeFilter.FILTER_REJECT;
                }
                if (parent.closest('nav[aria-label="Table of contents"]')) {
                    return NodeFilter.FILTER_REJECT;
                }
                if (!node.nodeValue || !node.nodeValue.trim()) return NodeFilter.FILTER_REJECT;
                return NodeFilter.FILTER_ACCEPT;
            },
        });
        let n;
        while ((n = walker.nextNode())) nodes.push(n);
        return nodes;
    }

    function findFirstMatch(nodes, needle) {
        const lowerNeedle = needle.toLowerCase();
        for (const node of nodes) {
            const idx = node.nodeValue.toLowerCase().indexOf(lowerNeedle);
            if (idx !== -1) return { node: node, idx: idx, length: needle.length };
        }
        return null;
    }

    function highlightMatch(match) {
        const range = document.createRange();
        range.setStart(match.node, match.idx);
        range.setEnd(match.node, match.idx + match.length);

        const mark = document.createElement("mark");
        mark.id = "docs-search-hl";
        mark.style.cssText =
            "background: rgba(165, 128, 250, 0.35); color: inherit; " +
            "border-radius: 3px; padding: 0 2px; box-shadow: 0 0 0 1px rgba(165, 128, 250, 0.5);";
        try {
            range.surroundContents(mark);
        } catch (e) {
            // The match range straddles element boundaries (e.g. half in
            // a <strong>, half out) -- skip highlighting rather than risk
            // corrupting the DOM with a partial-node wrap.
            return null;
        }
        return mark;
    }

    function run() {
        const query = getHighlightQuery();
        if (!query) return;

        const root = document.querySelector("main") || document.body;
        const nodes = collectTextNodes(root);

        let match = findFirstMatch(nodes, query);
        if (!match) {
            const tokens = tokenize(query);
            for (let i = 0; i < tokens.length && !match; i++) {
                match = findFirstMatch(nodes, tokens[i]);
            }
        }

        if (match) {
            const mark = highlightMatch(match);
            if (mark) {
                mark.scrollIntoView({ block: "center" });
                // These pages load Tailwind via CDN (<script src="https://
                // cdn.tailwindcss.com...">), which JIT-compiles and injects
                // styles asynchronously -- the resulting layout shift can
                // land after this script's own DOMContentLoaded scroll,
                // throwing the position off. One corrective re-scroll once
                // things have had a moment to settle; harmless if nothing
                // shifted (scrollIntoView on an already-centered element is
                // a no-op).
                window.setTimeout(function () {
                    mark.scrollIntoView({ block: "center" });
                }, 400);
            }
        }

        // Clean the param out of the visible URL -- a refresh shouldn't
        // redo the highlight, and the address bar stays readable.
        const url = new URL(window.location.href);
        url.searchParams.delete("hl");
        window.history.replaceState(null, "", url.pathname + url.search + url.hash);
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", run);
    } else {
        run();
    }
})();
