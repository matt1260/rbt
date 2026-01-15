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
    const typeInput = document.getElementById('typeInput');
    const hebrewKeyboard = document.getElementById('hebrewKeyboard');
    const greekKeyboard = document.getElementById('greekKeyboard');
    const hebrewKbdBtn = document.getElementById('hebrewKbdBtn');
    const greekKbdBtn = document.getElementById('greekKbdBtn');
    
    // State
    let debounceTimer = null;
    let currentRequest = null;
    let activeKeyboard = null;
    let currentSearchType = 'keyword'; // track current tab selection
    
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
        
        // Form submit handler - detect chapter-only references and redirect
        if (searchForm) {
            searchForm.addEventListener('submit', (e) => {
                if (currentSearchType === 'reference') {
                    const query = searchInput.value.trim();
                    const chapterMatch = parseChapterReference(query);
                    if (chapterMatch) {
                        e.preventDefault();
                        // Redirect directly to the chapter
                        window.location.href = `/?book=${encodeURIComponent(chapterMatch.book)}&chapter=${chapterMatch.chapter}`;
                        return;
                    }
                }
            });
        }
        
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
        
        // Update current search type for API calls
        if (type === 'reference') {
            currentSearchType = 'reference';
        } else if (type === 'keyword' || type === 'hebrew' || type === 'greek') {
            currentSearchType = 'keyword';
        }
        
        // Update hidden type input
        if (typeInput) {
            typeInput.value = currentSearchType;
        }
        
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
        
        // Re-trigger search if there's content
        if (searchInput && searchInput.value.length >= 2) {
            performSearch(searchInput.value);
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
        const searchType = currentSearchType || 'keyword';
        
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
                `/api/live/?q=${encodeURIComponent(query)}&scope=${scope}&limit=50&type=${searchType}`,
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
                            <span class="source-badge">${escapeHtml(r.book || '')} ${r.chapter}:${r.verse}</span>
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
            html += `<div class="results-category"><i class="fas fa-open-book"></i> New Testament (${counts.nt_verses})</div>`;
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
                            <span class="source-badge">${escapeHtml(r.book || '')} ${r.chapter}:${r.verse}</span>
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
        const searchTypeParam = currentSearchType || 'keyword';
        html += `
            <a href="/search/results/?q=${encodeURIComponent(query)}&scope=${data.scope}&page=1&type=${searchTypeParam}" class="view-all-results">
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
                    ${r.version ? `<span class="source-badge" style="background-color: #e3c997;">${escapeHtml(r.version)}</span>` : ''}
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
    
    // Parse chapter-only reference like "Mark 10", "Genesis 20", "1 Samuel 5"
    function parseChapterReference(query) {
        if (!query) return null;
        
        // List of valid Bible book names
        const bookNames = [
            // Old Testament
            'genesis', 'gen', 'exodus', 'ex', 'exod', 'leviticus', 'lev', 'numbers', 'num',
            'deuteronomy', 'deut', 'deu', 'joshua', 'josh', 'judges', 'judg', 'ruth',
            '1 samuel', '1samuel', '1 sam', '1sam', '2 samuel', '2samuel', '2 sam', '2sam',
            '1 kings', '1kings', '1 ki', '1ki', '2 kings', '2kings', '2 ki', '2ki',
            '1 chronicles', '1chronicles', '1 chr', '1chr', '2 chronicles', '2chronicles', '2 chr', '2chr',
            'ezra', 'nehemiah', 'neh', 'esther', 'est', 'job', 'psalms', 'psalm', 'ps', 'psa',
            'proverbs', 'prov', 'pro', 'ecclesiastes', 'eccl', 'ecc', 'song of solomon', 'song', 'sos',
            'isaiah', 'isa', 'jeremiah', 'jer', 'lamentations', 'lam', 'ezekiel', 'ezek', 'eze',
            'daniel', 'dan', 'hosea', 'hos', 'joel', 'amos', 'obadiah', 'obad', 'oba',
            'jonah', 'jon', 'micah', 'mic', 'nahum', 'nah', 'habakkuk', 'hab',
            'zephaniah', 'zeph', 'zep', 'haggai', 'hag', 'zechariah', 'zech', 'zec', 'malachi', 'mal',
            // New Testament
            'matthew', 'matt', 'mat', 'mark', 'mar', 'mk', 'luke', 'luk', 'john', 'joh', 'jn',
            'acts', 'act', 'romans', 'rom', '1 corinthians', '1corinthians', '1 cor', '1cor',
            '2 corinthians', '2corinthians', '2 cor', '2cor', 'galatians', 'gal',
            'ephesians', 'eph', 'philippians', 'phil', 'colossians', 'col',
            '1 thessalonians', '1thessalonians', '1 thess', '1thess', '2 thessalonians', '2thessalonians', '2 thess', '2thess',
            '1 timothy', '1timothy', '1 tim', '1tim', '2 timothy', '2timothy', '2 tim', '2tim',
            'titus', 'tit', 'philemon', 'phm', 'hebrews', 'heb', 'james', 'jas', 'jam',
            '1 peter', '1peter', '1 pet', '1pet', '2 peter', '2peter', '2 pet', '2pet',
            '1 john', '1john', '1 jn', '1jn', '2 john', '2john', '2 jn', '2jn', '3 john', '3john', '3 jn', '3jn',
            'jude', 'revelation', 'rev'
        ];
        
        // Book name to canonical name mapping
        const bookMapping = {
            'gen': 'Genesis', 'genesis': 'Genesis',
            'ex': 'Exodus', 'exod': 'Exodus', 'exodus': 'Exodus',
            'lev': 'Leviticus', 'leviticus': 'Leviticus',
            'num': 'Numbers', 'numbers': 'Numbers',
            'deut': 'Deuteronomy', 'deu': 'Deuteronomy', 'deuteronomy': 'Deuteronomy',
            'josh': 'Joshua', 'joshua': 'Joshua',
            'judg': 'Judges', 'judges': 'Judges',
            'ruth': 'Ruth',
            '1 samuel': '1 Samuel', '1samuel': '1 Samuel', '1 sam': '1 Samuel', '1sam': '1 Samuel',
            '2 samuel': '2 Samuel', '2samuel': '2 Samuel', '2 sam': '2 Samuel', '2sam': '2 Samuel',
            '1 kings': '1 Kings', '1kings': '1 Kings', '1 ki': '1 Kings', '1ki': '1 Kings',
            '2 kings': '2 Kings', '2kings': '2 Kings', '2 ki': '2 Kings', '2ki': '2 Kings',
            '1 chronicles': '1 Chronicles', '1chronicles': '1 Chronicles', '1 chr': '1 Chronicles', '1chr': '1 Chronicles',
            '2 chronicles': '2 Chronicles', '2chronicles': '2 Chronicles', '2 chr': '2 Chronicles', '2chr': '2 Chronicles',
            'ezra': 'Ezra',
            'neh': 'Nehemiah', 'nehemiah': 'Nehemiah',
            'est': 'Esther', 'esther': 'Esther',
            'job': 'Job',
            'ps': 'Psalms', 'psa': 'Psalms', 'psalm': 'Psalms', 'psalms': 'Psalms',
            'prov': 'Proverbs', 'pro': 'Proverbs', 'proverbs': 'Proverbs',
            'eccl': 'Ecclesiastes', 'ecc': 'Ecclesiastes', 'ecclesiastes': 'Ecclesiastes',
            'song of solomon': 'Song of Solomon', 'song': 'Song of Solomon', 'sos': 'Song of Solomon',
            'isa': 'Isaiah', 'isaiah': 'Isaiah',
            'jer': 'Jeremiah', 'jeremiah': 'Jeremiah',
            'lam': 'Lamentations', 'lamentations': 'Lamentations',
            'ezek': 'Ezekiel', 'eze': 'Ezekiel', 'ezekiel': 'Ezekiel',
            'dan': 'Daniel', 'daniel': 'Daniel',
            'hos': 'Hosea', 'hosea': 'Hosea',
            'joel': 'Joel',
            'amos': 'Amos',
            'obad': 'Obadiah', 'oba': 'Obadiah', 'obadiah': 'Obadiah',
            'jon': 'Jonah', 'jonah': 'Jonah',
            'mic': 'Micah', 'micah': 'Micah',
            'nah': 'Nahum', 'nahum': 'Nahum',
            'hab': 'Habakkuk', 'habakkuk': 'Habakkuk',
            'zeph': 'Zephaniah', 'zep': 'Zephaniah', 'zephaniah': 'Zephaniah',
            'hag': 'Haggai', 'haggai': 'Haggai',
            'zech': 'Zechariah', 'zec': 'Zechariah', 'zechariah': 'Zechariah',
            'mal': 'Malachi', 'malachi': 'Malachi',
            // New Testament
            'matt': 'Matthew', 'mat': 'Matthew', 'matthew': 'Matthew',
            'mark': 'Mark', 'mar': 'Mark', 'mk': 'Mark',
            'luke': 'Luke', 'luk': 'Luke',
            'john': 'John', 'joh': 'John', 'jn': 'John',
            'acts': 'Acts', 'act': 'Acts',
            'rom': 'Romans', 'romans': 'Romans',
            '1 corinthians': '1 Corinthians', '1corinthians': '1 Corinthians', '1 cor': '1 Corinthians', '1cor': '1 Corinthians',
            '2 corinthians': '2 Corinthians', '2corinthians': '2 Corinthians', '2 cor': '2 Corinthians', '2cor': '2 Corinthians',
            'gal': 'Galatians', 'galatians': 'Galatians',
            'eph': 'Ephesians', 'ephesians': 'Ephesians',
            'phil': 'Philippians', 'philippians': 'Philippians',
            'col': 'Colossians', 'colossians': 'Colossians',
            '1 thessalonians': '1 Thessalonians', '1thessalonians': '1 Thessalonians', '1 thess': '1 Thessalonians', '1thess': '1 Thessalonians',
            '2 thessalonians': '2 Thessalonians', '2thessalonians': '2 Thessalonians', '2 thess': '2 Thessalonians', '2thess': '2 Thessalonians',
            '1 timothy': '1 Timothy', '1timothy': '1 Timothy', '1 tim': '1 Timothy', '1tim': '1 Timothy',
            '2 timothy': '2 Timothy', '2timothy': '2 Timothy', '2 tim': '2 Timothy', '2tim': '2 Timothy',
            'tit': 'Titus', 'titus': 'Titus',
            'phm': 'Philemon', 'philemon': 'Philemon',
            'heb': 'Hebrews', 'hebrews': 'Hebrews',
            'jas': 'James', 'jam': 'James', 'james': 'James',
            '1 peter': '1 Peter', '1peter': '1 Peter', '1 pet': '1 Peter', '1pet': '1 Peter',
            '2 peter': '2 Peter', '2peter': '2 Peter', '2 pet': '2 Peter', '2pet': '2 Peter',
            '1 john': '1 John', '1john': '1 John', '1 jn': '1 John', '1jn': '1 John',
            '2 john': '2 John', '2john': '2 John', '2 jn': '2 John', '2jn': '2 John',
            '3 john': '3 John', '3john': '3 John', '3 jn': '3 John', '3jn': '3 John',
            'jude': 'Jude',
            'rev': 'Revelation', 'revelation': 'Revelation'
        };
        
        const q = query.toLowerCase().trim();
        
        // Pattern: "Book Chapter" without verse (e.g., "Mark 10", "Genesis 20", "1 Samuel 5")
        // Must NOT have a colon (which would indicate a verse)
        if (q.includes(':')) return null;
        
        // Match patterns like "mark 10", "genesis 20", "1 samuel 5", "1 cor 13"
        const match = q.match(/^(\d?\s*[a-z]+(?:\s+of\s+[a-z]+)?)\s+(\d+)$/i);
        if (!match) return null;
        
        const bookPart = match[1].toLowerCase().trim();
        const chapter = parseInt(match[2], 10);
        
        // Check if book is valid
        const canonicalBook = bookMapping[bookPart];
        if (!canonicalBook) return null;
        
        return { book: canonicalBook, chapter: chapter };
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
