/**
 * Real Bible Search - Live Search JavaScript
 * Handles Hebrew/Greek keyboards, live AJAX search, and result display
 */

(function() {
    'use strict';
    
    // Elements
    const searchInput = document.getElementById('searchInput');
    const searchInputField = document.getElementById('searchInputField');
    const liveResults = document.getElementById('liveResults');
    const searchForm = document.getElementById('searchForm');
    const scopeInput = document.getElementById('scopeInput');
    const hebrewKeyboard = document.getElementById('hebrewKeyboard');
    const greekKeyboard = document.getElementById('greekKeyboard');
    const hebrewKbdBtn = document.getElementById('hebrewKbdBtn');
    const greekKbdBtn = document.getElementById('greekKbdBtn');
    
    // State
    let debounceTimer = null;
    let currentRequest = null;
    let activeKeyboard = null;
    
    // Initialize when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
    
    function init() {
        if (!searchInput) return; // Exit if not on search page
        
        // Search tabs
        document.querySelectorAll('.search-tab').forEach(tab => {
            tab.addEventListener('click', handleTabClick);
        });
        
        // Scope options
        document.querySelectorAll('.scope-option').forEach(option => {
            option.addEventListener('click', handleScopeClick);
        });
        
        // Keyboard toggle buttons
        if (hebrewKbdBtn) {
            hebrewKbdBtn.addEventListener('click', () => {
                if (activeKeyboard === 'hebrew') {
                    closeKeyboard('hebrew');
                } else {
                    openKeyboard('hebrew');
                }
            });
        }
        
        if (greekKbdBtn) {
            greekKbdBtn.addEventListener('click', () => {
                if (activeKeyboard === 'greek') {
                    closeKeyboard('greek');
                } else {
                    openKeyboard('greek');
                }
            });
        }
        
        // Virtual keyboard keys
        document.querySelectorAll('.key').forEach(key => {
            key.addEventListener('click', handleKeyClick);
        });
        
        // Live search on input
        searchInput.addEventListener('input', handleSearchInput);
        
        // Focus/blur handlers
        searchInput.addEventListener('focus', () => {
            if (searchInput.value.length >= 2 && liveResults.innerHTML) {
                liveResults.classList.add('active');
            }
        });
        
        // Close results on outside click
        document.addEventListener('click', (e) => {
            if (!e.target.closest('.search-input-container')) {
                hideResults();
            }
        });
        
        // Keyboard navigation
        searchInput.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                hideResults();
                closeAllKeyboards();
            }
        });
        
        // Check if there's a query parameter in URL and trigger search
        const urlParams = new URLSearchParams(window.location.search);
        const queryParam = urlParams.get('q');
        const scopeParam = urlParams.get('scope');
        
        if (queryParam) {
            searchInput.value = queryParam;
            if (scopeParam && scopeInput) {
                scopeInput.value = scopeParam;
                // Update active scope button
                document.querySelectorAll('.scope-option').forEach(opt => {
                    opt.classList.toggle('active', opt.dataset.scope === scopeParam);
                });
            }
            // Trigger search automatically
            performSearch(queryParam);
        }
    }
    
    function handleTabClick(e) {
        const tab = e.currentTarget;
        document.querySelectorAll('.search-tab').forEach(t => t.classList.remove('active'));
        tab.classList.add('active');
        
        const type = tab.dataset.type;
        if (type === 'hebrew') {
            openKeyboard('hebrew');
            searchInput.placeholder = 'Enter Hebrew text...';
            searchInput.classList.add('rtl-input');
        } else if (type === 'greek') {
            openKeyboard('greek');
            searchInput.placeholder = 'Enter Greek text...';
            searchInput.classList.add('greek-input');
            searchInput.classList.remove('rtl-input');
        } else {
            closeAllKeyboards();
            searchInput.classList.remove('rtl-input', 'greek-input');
            searchInput.placeholder = type === 'reference' 
                ? 'Enter reference (e.g., John 3:16, Gen 1:1-5)...'
                : 'Enter search term...';
        }
    }
    
    function handleScopeClick(e) {
        const option = e.currentTarget;
        document.querySelectorAll('.scope-option').forEach(o => o.classList.remove('active'));
        option.classList.add('active');
        scopeInput.value = option.dataset.scope;
        
        // Re-trigger search if there's content
        if (searchInput.value.length >= 2) {
            performSearch(searchInput.value);
        }
    }
    
    function handleKeyClick(e) {
        const key = e.currentTarget;
        const char = key.dataset.char;
        const action = key.dataset.action;
        
        if (action === 'backspace') {
            searchInput.value = searchInput.value.slice(0, -1);
        } else if (action === 'clear') {
            searchInput.value = '';
        } else if (char) {
            searchInput.value += char;
        }
        
        searchInput.focus();
        
        // Trigger search
        if (searchInput.value.length >= 2) {
            clearTimeout(debounceTimer);
            debounceTimer = setTimeout(() => performSearch(searchInput.value), 300);
        }
    }
    
    function handleSearchInput(e) {
        const query = e.target.value.trim();
        
        // Detect script and adjust input
        if (hasHebrew(query)) {
            searchInput.classList.add('rtl-input');
        } else if (hasGreek(query)) {
            searchInput.classList.add('greek-input');
            searchInput.classList.remove('rtl-input');
        } else {
            searchInput.classList.remove('rtl-input', 'greek-input');
        }
        
        clearTimeout(debounceTimer);
        
        if (query.length < 2) {
            hideResults();
            return;
        }
        
        debounceTimer = setTimeout(() => performSearch(query), 300);
    }
    
    // Perform live search
    async function performSearch(query) {
        const scope = scopeInput ? scopeInput.value : 'all';
        
        // Show loading state
        if (searchInputField) {
            searchInputField.classList.add('loading');
        }
        
        // Cancel previous request
        if (currentRequest) {
            currentRequest.abort();
        }
        
        currentRequest = new AbortController();
        
        try {
            const response = await fetch(
                `/api/live/?q=${encodeURIComponent(query)}&scope=${scope}&limit=50`,
                { signal: currentRequest.signal }
            );
            
            const data = await response.json();
            displayResults(data);
            
        } catch (error) {
            if (error.name !== 'AbortError') {
                console.error('Search error:', error);
                liveResults.innerHTML = `
                    <div class="no-results">
                        <i class="fas fa-exclamation-circle"></i>
                        <p>Search error. Please try again.</p>
                    </div>
                `;
                liveResults.classList.add('active');
            }
        } finally {
            if (searchInputField) {
                searchInputField.classList.remove('loading');
            }
        }
    }
    
    // Display search results
    function displayResults(data) {
        if (data.error) {
            liveResults.innerHTML = `
                <div class="no-results">
                    <i class="fas fa-exclamation-circle"></i>
                    <p>${data.error}</p>
                </div>
            `;
            liveResults.classList.add('active');
            return;
        }
        
        const { results, counts, total, query } = data;
        
        if (total === 0) {
            liveResults.innerHTML = `
                <div class="no-results">
                    <i class="fas fa-search"></i>
                    <p>No results found for "${escapeHtml(query)}"</p>
                </div>
            `;
            liveResults.classList.add('active');
            return;
        }
        
        let html = `
            <div class="results-meta">
                <span><strong>${total}</strong> results found</span>
                <span style="font-size: 11px; color: #999;">
                    ${data.script_detected && data.script_detected.hebrew ? '🔤 Hebrew' : ''}
                    ${data.script_detected && data.script_detected.greek ? '🔤 Greek' : ''}
                </span>
            </div>
        `;
        
        // References
        if (results.references && results.references.length > 0) {
            html += `<div class="results-category"><i class="fas fa-bookmark"></i> Reference Match</div>`;
            results.references.forEach(r => {
                html += `
                    <a href="${r.url}" class="result-item">
                        <div class="result-reference">
                            <i class="fas fa-book-open"></i> ${escapeHtml(r.display)}
                        </div>
                    </a>
                `;
            });
        }
        
        // OT Verses
        if (results.ot_verses && results.ot_verses.length > 0) {
            html += `<div class="results-category"><i class="fas fa-scroll"></i> Old Testament (${counts.ot_verses})</div>`;
            results.ot_verses.slice(0, 5).forEach(r => {
                html += renderResultItem(r, 'ot_verse');
            });
        }
        
        // Hebrew Words
        if (results.ot_hebrew && results.ot_hebrew.length > 0) {
            html += `<div class="results-category"><i class="fas fa-font"></i> Hebrew Words (${counts.ot_hebrew})</div>`;
            results.ot_hebrew.slice(0, 5).forEach(r => {
                html += `
                    <a href="${r.url || '#'}" class="result-item">
                        <div class="result-reference">
                            <span style="font-family: 'SBL Hebrew', serif; font-size: 18px;">${escapeHtml(r.hebrew_niqqud || r.hebrew || '')}</span>
                            <span class="source-badge">${r.book} ${r.chapter}:${r.verse}</span>
                        </div>
                        <div class="result-preview">
                            <strong>English:</strong> ${escapeHtml(r.english || '')}
                        </div>
                        <div class="result-meta">
                            ${r.strongs ? `<span style="font-size: 11px;">${parseStrongs(r.strongs)}</span>` : ''}
                            ${r.morphology ? `<span>Morph: ${r.morphology}</span>` : ''}
                        </div>
                    </a>
                `;
            });
        }
        
        // NT Verses
        if (results.nt_verses && results.nt_verses.length > 0) {
            html += `<div class="results-category"><i class="fas fa-cross"></i> New Testament (${counts.nt_verses})</div>`;
            results.nt_verses.slice(0, 5).forEach(r => {
                html += renderResultItem(r, 'nt_verse');
            });
        }
        
        // Greek Words
        if (results.nt_greek && results.nt_greek.length > 0) {
            html += `<div class="results-category"><i class="fas fa-language"></i> Greek Words (${counts.nt_greek})</div>`;
            results.nt_greek.slice(0, 5).forEach(r => {
                html += `
                    <a href="${r.url || '#'}" class="result-item">
                        <div class="result-reference">
                            <span style="font-family: 'SBL Greek', serif; font-size: 18px;">${escapeHtml(r.lemma || r.greek || '')}</span>
                            <span style="font-style: italic; color: #666; margin-left: 8px;">${escapeHtml(r.translit || '')}</span>
                            <span class="source-badge">${r.book} ${r.chapter}:${r.verse}</span>
                        </div>
                        <div class="result-preview">
                            <strong>English:</strong> ${escapeHtml(r.english || '')}
                        </div>
                        <div class="result-meta">
                            ${r.strongs ? `<span>Strong's: G${r.strongs}</span>` : ''}
                            ${r.morph_desc ? `<span>${r.morph_desc}</span>` : (r.morphology ? `<span>${r.morphology}</span>` : '')}
                        </div>
                    </a>
                `;
            });
        }
        
        // Footnotes
        if (results.footnotes && results.footnotes.length > 0) {
            html += `<div class="results-category"><i class="fas fa-sticky-note"></i> Footnotes (${counts.footnotes})</div>`;
            results.footnotes.slice(0, 5).forEach(r => {
                html += `
                    <a href="${r.url || '#'}" class="result-item">
                        <div class="result-reference">
                            <i class="fas fa-sticky-note"></i> ${escapeHtml(r.book)} ${r.chapter}:${r.verse}
                            <span class="source-badge">footnote</span>
                        </div>
                        <div class="result-preview">${r.text || ''}</div>
                    </a>
                `;
            });
        }
        
        // View all link
        html += `
            <a href="/search/results/?q=${encodeURIComponent(query)}&scope=${data.scope}&page=1" class="view-all-results">
                <i class="fas fa-arrow-right"></i> View All ${total.toLocaleString()} Results
            </a>
        `;
        
        liveResults.innerHTML = html;
        liveResults.classList.add('active');
    }
    
    function renderResultItem(r, type) {
        return `
            <a href="${r.url || '#'}" class="result-item">
                <div class="result-reference">
                    <i class="fas fa-book-open"></i> ${escapeHtml(r.book)} ${r.chapter}:${r.verse}
                    <span class="source-badge">${type === 'ot_verse' ? 'OT' : 'NT'}</span>
                </div>
                <div class="result-preview">${r.text || ''}</div>
            </a>
        `;
    }
    
    function hideResults() {
        if (liveResults) {
            liveResults.classList.remove('active');
        }
    }
    
    // Keyboard functions
    function openKeyboard(type) {
        closeAllKeyboards();
        
        if (type === 'hebrew' && hebrewKeyboard) {
            hebrewKeyboard.classList.add('active');
            if (hebrewKbdBtn) hebrewKbdBtn.classList.add('active');
            searchInput.classList.add('rtl-input');
            activeKeyboard = 'hebrew';
        } else if (type === 'greek' && greekKeyboard) {
            greekKeyboard.classList.add('active');
            if (greekKbdBtn) greekKbdBtn.classList.add('active');
            searchInput.classList.add('greek-input');
            activeKeyboard = 'greek';
        }
        
        if (searchInput) searchInput.focus();
    }
    
    // Global function for close buttons
    window.closeKeyboard = function(type) {
        if (type === 'hebrew' && hebrewKeyboard) {
            hebrewKeyboard.classList.remove('active');
            if (hebrewKbdBtn) hebrewKbdBtn.classList.remove('active');
            if (searchInput) searchInput.classList.remove('rtl-input');
        } else if (type === 'greek' && greekKeyboard) {
            greekKeyboard.classList.remove('active');
            if (greekKbdBtn) greekKbdBtn.classList.remove('active');
            if (searchInput) searchInput.classList.remove('greek-input');
        }
        activeKeyboard = null;
    };
    
    function closeAllKeyboards() {
        if (hebrewKeyboard) hebrewKeyboard.classList.remove('active');
        if (greekKeyboard) greekKeyboard.classList.remove('active');
        if (hebrewKbdBtn) hebrewKbdBtn.classList.remove('active');
        if (greekKbdBtn) greekKbdBtn.classList.remove('active');
        if (searchInput) {
            searchInput.classList.remove('rtl-input');
            searchInput.classList.remove('greek-input');
        }
        activeKeyboard = null;
    }
    
    // Utility functions
    function hasHebrew(text) {
        return /[\u0590-\u05FF]/.test(text);
    }
    
    function hasGreek(text) {
        return /[\u0370-\u03FF\u1F00-\u1FFF]/.test(text);
    }
    
    function escapeHtml(text) {
        if (!text) return '';
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
    
    function parseStrongs(strongsData) {
        if (!strongsData) return '';
        
        // Parse format like: "H9001=ו=seq/H1961=הָיָה=to be/H9014=־=link"
        const entries = strongsData.split('/');
        const parsed = entries.map(entry => {
            const parts = entry.split('=');
            if (parts.length >= 3) {
                const num = parts[0]; // e.g., H9001
                const hebrew = parts[1]; // e.g., ו
                const gloss = parts.slice(2).join('=').split('_§')[0].split('@')[0]; // e.g., "seq" from "seq_§..."
                return `<span title="${escapeHtml(entry)}">${num}: ${gloss}</span>`;
            }
            return escapeHtml(entry);
        });
        
        return parsed.slice(0, 3).join(' + ') + (entries.length > 3 ? ` <small>(+${entries.length - 3} more)</small>` : '');
    }
    
})();
