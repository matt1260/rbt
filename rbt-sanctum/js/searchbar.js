(function() {
    'use strict';
    
    // Configuration
    const API_BASE = 'https://read.realbible.tech';
    const DEBOUNCE_MS = 500;
    const MIN_CHARS = 2;
    
    let debounceTimer = null;
    let retryTimer = null;
    let retryCount = 0;
    const MAX_RETRIES = 24;
    
    // Wait for DOM ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initWithRetry, { once: true });
    } else {
        initWithRetry();
    }

    window.initRBTSearch = initRBTSearch;

    function initWithRetry() {
        const ok = initRBTSearch();
        if (ok) return;

        if (retryTimer) clearTimeout(retryTimer);
        if (retryCount >= MAX_RETRIES) return;

        retryCount += 1;
        retryTimer = setTimeout(initWithRetry, 250);
    }
    
    function initRBTSearch() {
        const searchInput = document.getElementById('rbtSearchInput');
        const searchForm = document.getElementById('rbtSearchForm');
        const liveResults = document.getElementById('rbtLiveResults');
        
        if (!searchInput || !searchForm || !liveResults) {
            return false;
        }

        if (searchForm.dataset.rbtBound === '1') {
            return true;
        }

        searchForm.dataset.rbtBound = '1';
        
        // Live search input
        searchInput.addEventListener('input', function() {
            handleSearchInput(this.value);
        });
        
        // Close dropdown on outside click
        document.addEventListener('click', function(e) {
            if (!searchInput.contains(e.target) && !liveResults.contains(e.target)) {
                liveResults.classList.remove('active');
            }
        });
        
        // Form submit
        searchForm.addEventListener('submit', function(e) {
            const query = searchInput.value.trim();
            if (!query) {
                e.preventDefault();
                return;
            }
            
            // Check for chapter-only reference (e.g., "Mark 10", "Genesis 20")
            const chapterMatch = parseChapterReference(query);
            if (chapterMatch) {
                e.preventDefault();
                // Redirect directly to the chapter page
                window.location.href = `${API_BASE}/?book=${encodeURIComponent(chapterMatch.book)}&chapter=${chapterMatch.chapter}`;
                return;
            }
            
            liveResults.classList.remove('active');
        });
        
        // Keyboard navigation
        searchInput.addEventListener('keydown', function(e) {
            if (e.key === 'Escape') {
                liveResults.classList.remove('active');
            }
        });
        
        // Focus shows results if available
        searchInput.addEventListener('focus', function() {
            if (this.value.trim().length >= MIN_CHARS && liveResults.innerHTML) {
                liveResults.classList.add('active');
            }
        });
        
        console.log('RBT Search initialized');
        return true;
    }
    
    function handleSearchInput(value) {
        const query = value.trim();
        const liveResults = document.getElementById('rbtLiveResults');
        
        clearTimeout(debounceTimer);
        
        if (query.length < MIN_CHARS) {
            liveResults.classList.remove('active');
            return;
        }
        
        debounceTimer = setTimeout(function() {
            performSearch(query);
        }, DEBOUNCE_MS);
    }
    
    function performSearch(query) {
        const inputField = document.getElementById('rbtSearchInputField');
        const liveResults = document.getElementById('rbtLiveResults');
        
        inputField.classList.add('loading');
        
        // Let the API auto-detect reference vs keyword
        fetch(`${API_BASE}/api/live/?q=${encodeURIComponent(query)}&scope=all&limit=50`)
            .then(response => {
                if (!response.ok) throw new Error('Network response was not ok');
                return response.json();
            })
            .then(data => {
                inputField.classList.remove('loading');
                displayResults(data, query);
            })
            .catch(error => {
                console.error('RBT Search Error:', error);
                inputField.classList.remove('loading');
                displayError();
            });
    }
    
    function displayResults(data, query) {
        const liveResults = document.getElementById('rbtLiveResults');
        let html = '';
        
        // API returns: data.results.{ot_verses, nt_verses, etc} and data.counts.{ot_verses, etc}
        const results = data.results || {};
        const counts = data.counts || {};
        const total = data.total || 0;
        
        if (total === 0) {
            html = `
                <div class="rbt-no-results">
                    <i class="fas fa-search"></i>
                    <div>No results found for "<strong>${escapeHtml(query)}</strong>"</div>
                    <div style="margin-top: 10px; font-size: 13px;">Try different keywords or a Bible reference like "John 3:16"</div>
                </div>
            `;
            liveResults.innerHTML = html;
            liveResults.classList.add('active');
            return;
        }
        
        // Results meta
        html += `
            <div class="rbt-results-meta">
                <span><strong>${total.toLocaleString()}</strong> results found</span>
                <span>Press Enter for all results</span>
            </div>
        `;
        
        // Reference matches
        if (results.references && results.references.length > 0) {
            html += `<div class="rbt-results-category"><i class="fas fa-bookmark"></i> Reference Match</div>`;
            results.references.forEach(ref => {
                const display = ref.display || `${ref.book} ${ref.chapter}${ref.verse ? ':' + ref.verse : ''}`;
                html += `
                    <a href="${API_BASE}${ref.url || '/search/?ref=' + encodeURIComponent(display)}" class="rbt-result-item">
                        <div class="rbt-result-reference">
                            <i class="fas fa-book-open"></i> ${escapeHtml(display)}
                        </div>
                        <div class="rbt-result-preview">Click to view this passage</div>
                    </a>
                `;
            });
        }
        
        // OT Verses
        if (results.ot_verses && results.ot_verses.length > 0) {
            html += `<div class="rbt-results-category"><i class="fas fa-scroll"></i> Old Testament (${(counts.ot_verses || results.ot_verses.length).toLocaleString()} matches)</div>`;
            results.ot_verses.slice(0, 5).forEach(verse => {
                const ref = `${verse.book} ${verse.chapter}:${verse.verse}`;
                html += `
                    <a href="${API_BASE}${verse.url || '/search/?ref=' + encodeURIComponent(ref)}" class="rbt-result-item">
                        <div class="rbt-result-reference">
                            ${escapeHtml(ref)}
                            <span class="rbt-source-badge">OT</span>
                        </div>
                        <div class="rbt-result-preview">${verse.text || ''}</div>
                    </a>
                `;
            });
        }
        
        // Hebrew Words
        if (results.ot_hebrew && results.ot_hebrew.length > 0) {
            html += `<div class="rbt-results-category"><i class="fas fa-language"></i> Hebrew Words (${(counts.ot_hebrew || results.ot_hebrew.length).toLocaleString()} matches)</div>`;
            results.ot_hebrew.slice(0, 5).forEach(word => {
                const ref = `${word.book} ${word.chapter}:${word.verse}`;
                // Parse strongs to get all numbers: "H9003=ב=in/H3068=יהוה=YHWH" -> "H9003 + H3068"
                let strongsDisplay = '';
                if (word.strongs) {
                    const parts = word.strongs.split('/');
                    const nums = parts.map(p => p.split('=')[0]).filter(n => n);
                    strongsDisplay = nums.join(' + ');
                }
                html += `
                    <a href="${API_BASE}${word.url || '/search/?ref=' + encodeURIComponent(ref)}" class="rbt-result-item">
                        <div class="rbt-result-reference">
                            <span class="rbt-hebrew">${word.hebrew_niqqud || word.hebrew || ''}</span>
                            <span class="rbt-source-badge">${escapeHtml(ref)}</span>
                        </div>
                        <div class="rbt-result-preview">
                            <strong>English:</strong> ${escapeHtml(word.english ? word.english.replace(/<[^>]*>/g, '') : '')}
                        </div>
                        <div class="rbt-result-meta">
                            <span>Strong's: ${escapeHtml(strongsDisplay)}</span>
                            <span>${escapeHtml(word.morphology || '')}</span>
                        </div>
                    </a>
                `;
            });
        }
        
        // NT Verses
        if (results.nt_verses && results.nt_verses.length > 0) {
            html += `<div class="rbt-results-category"><i class="fas fa-book-open"></i> New Testament (${(counts.nt_verses || results.nt_verses.length).toLocaleString()} matches)</div>`;
            results.nt_verses.slice(0, 5).forEach(verse => {
                const ref = `${verse.book} ${verse.chapter}:${verse.verse}`;
                html += `
                    <a href="${API_BASE}${verse.url || '/search/?ref=' + encodeURIComponent(ref)}" class="rbt-result-item">
                        <div class="rbt-result-reference">
                            ${escapeHtml(ref)}
                            <span class="rbt-source-badge">NT</span>
                        </div>
                        <div class="rbt-result-preview">${verse.text || ''}</div>
                    </a>
                `;
            });
        }
        
        // Greek Words
        if (results.nt_greek && results.nt_greek.length > 0) {
            html += `<div class="rbt-results-category"><i class="fas fa-language"></i> Greek Words (${(counts.nt_greek || results.nt_greek.length).toLocaleString()} matches)</div>`;
            results.nt_greek.slice(0, 5).forEach(word => {
                const ref = `${word.book} ${word.chapter}:${word.verse}`;
                html += `
                    <a href="${API_BASE}${word.url || '/search/?ref=' + encodeURIComponent(ref)}" class="rbt-result-item">
                        <div class="rbt-result-reference">
                            <span class="rbt-greek">${word.lemma || ''}</span>
                            <span style="font-style: italic; color: #666; margin-left: 8px;">${escapeHtml(word.translit || '')}</span>
                            <span class="rbt-source-badge">${escapeHtml(ref)}</span>
                        </div>
                        <div class="rbt-result-preview">
                            <strong>English:</strong> ${escapeHtml(word.english || '')}
                        </div>
                        <div class="rbt-result-meta">
                            <span>Strong's: G${escapeHtml(word.strongs || '')}</span>
                            <span>${escapeHtml(word.morph_desc || word.morphology || '')}</span>
                        </div>
                    </a>
                `;
            });
        }
        
        // Footnotes
        if (results.footnotes && results.footnotes.length > 0) {
            html += `<div class="rbt-results-category"><i class="fas fa-sticky-note"></i> Footnotes (${(counts.footnotes || results.footnotes.length).toLocaleString()} matches)</div>`;
            results.footnotes.slice(0, 3).forEach(note => {
                const ref = `${note.book} ${note.chapter}:${note.verse}`;
                html += `
                    <a href="${API_BASE}${note.url || '/search/?ref=' + encodeURIComponent(ref)}" class="rbt-result-item">
                        <div class="rbt-result-reference">
                            ${escapeHtml(ref)}
                            <span class="rbt-source-badge">Footnote</span>
                        </div>
                        <div class="rbt-result-preview">${note.text || ''}</div>
                    </a>
                `;
            });
        }
        
        // View All Results Link
        html += `
            <a href="${API_BASE}/search/results/?q=${encodeURIComponent(query)}&scope=all&page=1" class="rbt-view-all-results">
                <i class="fas fa-arrow-right"></i> View All ${total.toLocaleString()} Results
            </a>
        `;
        
        liveResults.innerHTML = html;
        liveResults.classList.add('active');
    }
    
    function displayError() {
        const liveResults = document.getElementById('rbtLiveResults');
        liveResults.innerHTML = `
            <div class="rbt-no-results">
                <i class="fas fa-exclamation-triangle"></i>
                <div>Unable to search. Please try again.</div>
            </div>
        `;
        liveResults.classList.add('active');
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
        
        // Pattern: "Book Chapter" without verse - must NOT have a colon
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
    
})();