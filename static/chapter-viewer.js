// Chapter viewer UI interactions
document.addEventListener("DOMContentLoaded", function() {
    // Parentheses toggle logic
    function wrapParenthesesText(element) {
        if (!element) return;
        function wrapTextNodes(node) {
            if (node.nodeType === Node.TEXT_NODE) {
                let replaced = node.textContent.replace(/\s\(\s*\"([^\"]+)\"\s*\)/g, function(match) {
                    return '<span class="paren-hide">' + match + '</span>';
                });
                if (replaced !== node.textContent) {
                    const temp = document.createElement('span');
                    temp.innerHTML = replaced;
                    while (temp.firstChild) {
                        node.parentNode.insertBefore(temp.firstChild, node);
                    }
                    node.parentNode.removeChild(node);
                }
            } else if (node.nodeType === Node.ELEMENT_NODE) {
                Array.from(node.childNodes).forEach(wrapTextNodes);
            }
        }
        wrapTextNodes(element);
    }

    // Prefer commonly used IDs but fall back to alternate IDs present in other templates
    const paraphraseEl = document.getElementById('paraphraseContainer') || document.getElementById('paraphrase-area') || document.getElementById('paraphrase');
    const literalEl = document.getElementById('literal-pane') || document.getElementById('literal-area') || document.getElementById('literal');

    wrapParenthesesText(paraphraseEl);
    wrapParenthesesText(literalEl);

    setTimeout(() => {
        document.querySelectorAll('.paren-hide').forEach(span => {
            span.style.setProperty('display', 'none', 'important');
        });
    }, 0);

    const literalToggleButton = document.getElementById("literalToggleButton");
    const imageToggleButton = document.getElementById("imageToggleButton");
    const h5ToggleButton = document.getElementById("h5ToggleButton");
    const verseRefToggleButton = document.getElementById("verseRefToggleButton");
    const parenthesesToggleButton = document.getElementById("parenthesesToggleButton");
    const notesToggleButton = document.getElementById("notesToggleButton");
    const toggleDivContainer = document.getElementById("toggleDivContainer");
    // Accept multiple possible IDs used across templates for the paraphrase/literal panes
    const paraphraseContainer = document.getElementById("paraphraseContainer") || document.getElementById("paraphrase-area") || document.getElementById("paraphrase");
    const container = document.getElementById("container") || document.getElementById("mainTextArea");
    const verseRefs = document.querySelectorAll(".verse_ref");
    const literalPane = document.getElementById("literal-pane") || document.getElementById("literal-area") || document.getElementById("literal");
    const notesPane = document.getElementById("notes-pane");
    const fontDecreaseButton = document.getElementById("fontDecreaseButton");
    const fontIncreaseButton = document.getElementById("fontIncreaseButton");
    
    const isMobile = window.innerWidth <= 768;
    
    // Font size management
    let currentFontSize = 100;
    const MIN_FONT_SIZE = 80;
    const MAX_FONT_SIZE = 150;
    const FONT_STEP = 10;
    
    function updateFontSize() {
        const targetContainer = document.getElementById('container') || document.getElementById('mainTextArea');
        if (targetContainer) {
            targetContainer.style.fontSize = currentFontSize + '%';
            localStorage.setItem('chapterFontSize', currentFontSize);
        }
    }
    
    const savedFontSize = localStorage.getItem('chapterFontSize');
    if (savedFontSize) {
        currentFontSize = parseInt(savedFontSize);
        updateFontSize();
    }
    
    let isLiteralVisible = false;
    let isImageVisible = true;
    let isH5Visible = true;
    let isVerseRefVisible = false;
    let isParenthesesVisible = false;
    let isNotesVisible = false;

    function updateLiteralButtonLabel() {
        if (literalToggleButton) {
            literalToggleButton.innerHTML = isLiteralVisible
                ? '<i class="fas fa-eye-slash"></i> Literal (L)'
                : '<i class="fas fa-eye"></i> Literal (L)';
        }
    }

    function updateLayout() {
        const isWideScreen = window.innerWidth > 768;

        if (notesToggleButton && toggleDivContainer && notesPane && literalPane && paraphraseContainer) {
            if (isNotesVisible) {
                notesPane.style.display = "block";
                literalPane.style.display = "none";
                toggleDivContainer.style.display = "block";
                paraphraseContainer.style.width = isWideScreen ? "50%" : "100%";
                notesToggleButton.innerHTML = '<i class="fas fa-book-open"></i> Notes (N)';
            } else {
                notesPane.style.display = "none";
                literalPane.style.display = isLiteralVisible ? "block" : "none";

                if (isLiteralVisible) {
                    toggleDivContainer.style.display = "block";
                    paraphraseContainer.style.width = isWideScreen ? "50%" : "100%";
                } else {
                    toggleDivContainer.style.display = "none";
                    paraphraseContainer.style.width = "100%";
                }

                notesToggleButton.innerHTML = '<i class="fas fa-book"></i> Notes (N)';
            }
        }

        updateLiteralButtonLabel();
    }

    updateLayout();
    
    function toggleVerseRefs() {
        verseRefs.forEach(function(ref) {
            ref.style.display = isVerseRefVisible ? "none" : "inline";
        });
        isVerseRefVisible = !isVerseRefVisible;
        if (verseRefToggleButton) {
            verseRefToggleButton.innerHTML = isVerseRefVisible 
                ? '<i class="fas fa-eye-slash"></i> Verse References (V)' 
                : '<i class="fas fa-eye"></i> Verse References (V)';
        }
    }

    if (literalToggleButton) {
        literalToggleButton.addEventListener("click", function() {
            if (isNotesVisible) {
                isNotesVisible = false;
                isLiteralVisible = true;
            } else {
                isLiteralVisible = !isLiteralVisible;
            }
            updateLayout();
        });
    }

    if (imageToggleButton) {
        imageToggleButton.addEventListener("click", function() {
            const tooltipContainers = document.querySelectorAll(".tooltip-container");
            tooltipContainers.forEach(function(container) {
                if (isImageVisible) {
                    container.style.display = "none";
                    imageToggleButton.innerHTML = '<i class="fas fa-eye"></i> Images (I)';
                } else {
                    container.style.display = "block";
                    imageToggleButton.innerHTML = '<i class="fas fa-eye-slash"></i> Images (I)';
                }
            });
            isImageVisible = !isImageVisible;
        });
    }

    if (verseRefToggleButton) {
        verseRefToggleButton.addEventListener("click", toggleVerseRefs);
    }

    if (notesToggleButton) {
        notesToggleButton.addEventListener("click", function() {
            isNotesVisible = !isNotesVisible;
            updateLayout();
        });
    }
    
    function toggleParentheses() {
        document.querySelectorAll('.paren-hide').forEach(span => {
            span.style.setProperty('display', isParenthesesVisible ? 'none' : 'inline', 'important');
        });
        isParenthesesVisible = !isParenthesesVisible;
        if (parenthesesToggleButton) {
            parenthesesToggleButton.innerHTML = isParenthesesVisible 
                ? '<i class="fas fa-eye-slash"></i> Names (P)' 
                : '<i class="fas fa-eye"></i> Names (P)';
        }
    }
    
    if (parenthesesToggleButton) {
        parenthesesToggleButton.addEventListener("click", toggleParentheses);
    }
    
    if (fontIncreaseButton) {
        fontIncreaseButton.addEventListener("click", function() {
            if (currentFontSize < MAX_FONT_SIZE) {
                currentFontSize += FONT_STEP;
                updateFontSize();
            }
        });
    }
    
    if (fontDecreaseButton) {
        fontDecreaseButton.addEventListener("click", function() {
            if (currentFontSize > MIN_FONT_SIZE) {
                currentFontSize -= FONT_STEP;
                updateFontSize();
            }
        });
    }

    function handleKeyDown(event) {
        if (event.target.tagName === 'INPUT' || event.target.tagName === 'TEXTAREA') return;
        
        if (event.key === "v") {
            toggleVerseRefs();
        } else if (event.key === "h" && h5ToggleButton) { 
            h5ToggleButton.click();
        } else if (event.key === "i") { 
            if (imageToggleButton) imageToggleButton.click();
        } else if (event.key === "l") { 
            if (literalToggleButton) literalToggleButton.click();
        } else if (event.key === "p") {
            toggleParentheses();
        } else if (event.key === "n") {
            if (notesToggleButton) notesToggleButton.click();
        } else if (event.key === "+" || event.key === "=") {
            if (fontIncreaseButton) fontIncreaseButton.click();
        } else if (event.key === "-" || event.key === "_") {
            if (fontDecreaseButton) fontDecreaseButton.click();
        }
    }
    document.addEventListener("keydown", handleKeyDown);

    window.addEventListener('resize', function() {
        const currentIsMobile = window.innerWidth <= 768;
        if (currentIsMobile !== isMobile) {
            location.reload();
        }
    });

    toggleVerseRefs();

    // Footnote zoom functionality
    const zoomOverlay = document.createElement('div');
    zoomOverlay.className = 'footnote-zoom-overlay';
    document.body.appendChild(zoomOverlay);

    const zoomContainer = document.createElement('div');
    zoomContainer.className = 'footnote-zoom-container';
    zoomContainer.innerHTML = `
        <div class="zoom-header">
            <span class="zoom-location"></span>
            <button class="zoom-close" aria-label="Close">&times;</button>
        </div>
        <div class="zoom-content"></div>
        <div class="zoom-hint">Press Escape or click outside to close</div>
    `;
    document.body.appendChild(zoomContainer);

    const zoomLocation = zoomContainer.querySelector('.zoom-location');
    const zoomContent = zoomContainer.querySelector('.zoom-content');
    const zoomClose = zoomContainer.querySelector('.zoom-close');

    function openFootnoteZoom(row) {
        const cells = row.querySelectorAll('td');
        if (cells.length < 2) return;

        const contentCell = cells[1];
        const locationEl = contentCell.querySelector('.note-location');
        const location = locationEl ? locationEl.textContent : '';
        
        let fullContent;
        if (contentCell.hasAttribute('data-full-content')) {
            fullContent = contentCell.getAttribute('data-full-content');
            const temp = document.createElement('div');
            temp.innerHTML = fullContent;
            const locEl = temp.querySelector('.note-location');
            if (locEl) locEl.remove();
            fullContent = temp.innerHTML;
        } else {
            const contentClone = contentCell.cloneNode(true);
            const locClone = contentClone.querySelector('.note-location');
            if (locClone) locClone.remove();
            fullContent = contentClone.innerHTML;
        }

        zoomLocation.textContent = location;
        zoomContent.innerHTML = fullContent;

        requestAnimationFrame(() => {
            zoomOverlay.classList.add('active');
            zoomContainer.classList.add('active');
            document.body.style.overflow = 'hidden';
        });
    }

    function closeFootnoteZoom() {
        zoomOverlay.classList.remove('active');
        zoomContainer.classList.remove('active');
        document.body.style.overflow = '';
    }

    function wrapFootnoteExcerpts() {
        const footnoteRows = document.querySelectorAll('#notes-pane .notes-table tr');
        footnoteRows.forEach(row => {
            const cells = row.querySelectorAll('td');
            if (cells.length < 2) return;
            
            const contentCell = cells[1];
            if (contentCell.querySelector('.footnote-excerpt')) return;
            
            const locationEl = contentCell.querySelector('.note-location');
            const excerptWrapper = document.createElement('div');
            excerptWrapper.className = 'footnote-excerpt';
            
            const fullContentHtml = contentCell.innerHTML;
            contentCell.setAttribute('data-full-content', fullContentHtml);
            
            Array.from(contentCell.childNodes).forEach(node => {
                if (node !== locationEl) {
                    excerptWrapper.appendChild(node.cloneNode(true));
                }
            });
            
            contentCell.innerHTML = '';
            if (locationEl) contentCell.appendChild(locationEl);
            contentCell.appendChild(excerptWrapper);
            
            const hint = document.createElement('div');
            hint.className = 'read-more-hint';
            hint.textContent = 'Tap to read full note';
            contentCell.appendChild(hint);
            
            requestAnimationFrame(() => {
                if (excerptWrapper.scrollHeight <= excerptWrapper.clientHeight + 5) {
                    excerptWrapper.classList.add('short');
                    hint.style.display = 'none';
                }
            });
        });
    }

    function attachFootnoteZoomListeners() {
        const footnoteRows = document.querySelectorAll('#notes-pane .notes-table tr');
        footnoteRows.forEach(row => {
            row.addEventListener('click', function(e) {
                if (e.target.tagName === 'A') return;
                openFootnoteZoom(row);
            });
        });
    }

    zoomClose.addEventListener('click', closeFootnoteZoom);
    zoomOverlay.addEventListener('click', closeFootnoteZoom);

    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape' && zoomContainer.classList.contains('active')) {
            closeFootnoteZoom();
        }
    });

    zoomContainer.addEventListener('click', function(e) {
        e.stopPropagation();
    });

    wrapFootnoteExcerpts();
    attachFootnoteZoomListeners();

    if (notesPane) {
        const notesObserver = new MutationObserver(function() {
            wrapFootnoteExcerpts();
            attachFootnoteZoomListeners();
        });
        notesObserver.observe(notesPane, { childList: true, subtree: true });
    }

    // Inline footnote popup system
    initializeFootnotePopups();
});

function initializeFootnotePopups() {
    let footnotePopupOverlay = document.createElement('div');
    footnotePopupOverlay.className = 'footnote-popup-overlay';
    document.body.appendChild(footnotePopupOverlay);

    let footnotePopup = document.createElement('div');
    footnotePopup.className = 'footnote-popup';
    footnotePopup.innerHTML = `
        <div class="footnote-popup-header">
            <h3 class="footnote-popup-title">Footnote</h3>
            <button class="footnote-popup-close" aria-label="Close">&times;</button>
        </div>
        <div class="footnote-popup-content"></div>
        <div class="footnote-popup-hint">Press Escape or click outside to close</div>
    `;
    document.body.appendChild(footnotePopup);

    const footnotePopupTitle = footnotePopup.querySelector('.footnote-popup-title');
    const footnotePopupContent = footnotePopup.querySelector('.footnote-popup-content');
    const footnotePopupClose = footnotePopup.querySelector('.footnote-popup-close');

    function sanitizeFootnoteContent(content) {
        try {
            const tmp = document.createElement('div');
            tmp.innerHTML = content || '';

            const secondTd = tmp.querySelector('td:nth-child(2)');
            if (secondTd) {
                const nl = secondTd.querySelector('.note-location');
                if (nl) nl.remove();
                return secondTd.innerHTML.trim();
            }

            const nl = tmp.querySelector('.note-location');
            if (nl) {
                nl.remove();
                return tmp.innerHTML.trim();
            }

            return content;
        } catch (e) {
            return content;
        }
    }

    function showFootnotePopup(footnoteId, content, title) {
        footnotePopupTitle.textContent = title || 'Footnote ' + footnoteId;
        const sanitized = sanitizeFootnoteContent(content || '<p>Loading footnote content...</p>');
        footnotePopupContent.innerHTML = sanitized;
        
        requestAnimationFrame(() => {
            footnotePopupOverlay.classList.add('active');
            footnotePopup.classList.add('active');
            document.body.style.overflow = 'hidden';
        });
    }

    function closeFootnotePopup() {
        footnotePopupOverlay.classList.remove('active');
        footnotePopup.classList.remove('active');
        document.body.style.overflow = '';
    }

    footnotePopupClose.addEventListener('click', function(e) {
        e.stopPropagation();
        closeFootnotePopup();
    });
    
    footnotePopupOverlay.addEventListener('click', closeFootnotePopup);
    
    footnotePopup.addEventListener('click', function(e) {
        e.stopPropagation();
    });

    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape' && footnotePopup.classList.contains('active')) {
            closeFootnotePopup();
        }
    });

    const footnoteCache = {};
    
    function preloadFootnoteData() {
        const allFootnoteLinks = document.querySelectorAll('a[href*="?footnote="]');
        const notesPane = document.getElementById('notes-pane');
        
        if (!notesPane) return;
        
        const notesTable = notesPane.querySelector('table');
        if (!notesTable) return;
        
        const verseToRows = {};
        const footnoteRows = notesTable.querySelectorAll('tr');
        
        footnoteRows.forEach((row, rowIndex) => {
            const cells = row.querySelectorAll('td');
            if (cells.length < 2) return;
            
            const verseRef = cells[0].textContent.trim();
            if (!verseRef) return;
            
            if (!verseToRows[verseRef]) {
                verseToRows[verseRef] = [];
            }
            
            const contentCell = cells[1];
            const locationEl = contentCell.querySelector('.note-location');
            const location = locationEl ? locationEl.textContent.trim() : verseRef;
            
            let content;
            if (contentCell.hasAttribute('data-full-content')) {
                content = contentCell.getAttribute('data-full-content');
            } else {
                const contentClone = contentCell.cloneNode(true);
                const locClone = contentClone.querySelector('.note-location');
                if (locClone) locClone.remove();
                content = contentClone.innerHTML;
            }
            
            verseToRows[verseRef].push({ location, content, rowIndex });
        });
        
        const linksByVerse = {};
        
        allFootnoteLinks.forEach(link => {
            const href = link.getAttribute('href');
            const match = href.match(/[?&]footnote=([^&]+)/);
            if (!match) return;
            
            const footnoteId = match[1];
            const parts = footnoteId.split('-');
            if (parts.length < 3) return;
            
            const book = parts[0];
            const chapter = parts[1];
            const verse = parts[2];
            const verseRef = `${book}. ${chapter}:${verse}`;
            
            if (!linksByVerse[verseRef]) {
                linksByVerse[verseRef] = [];
            }
            linksByVerse[verseRef].push(footnoteId);
        });
        
        Object.keys(linksByVerse).forEach(verseRef => {
            const footnoteIds = linksByVerse[verseRef];
            const rows = verseToRows[verseRef];
            
            if (!rows || rows.length === 0) return;
            
            footnoteIds.forEach((footnoteId, index) => {
                const rowIndex = Math.min(index, rows.length - 1);
                const sanitizedContent = sanitizeFootnoteContent(rows[rowIndex].content);
                footnoteCache[footnoteId] = {
                    title: rows[rowIndex].location,
                    content: sanitizedContent
                };
            });
        });
    }
    
    preloadFootnoteData();

    function attachFootnotePopupHandlers() {
        const footnoteLinks = document.querySelectorAll('a[href*="?footnote="]');
        
        footnoteLinks.forEach(link => {
            if (link.dataset.footnoteHandled) return;
            if (link.closest('#notes-pane')) return;
            
            link.dataset.footnoteHandled = 'true';
            
            link.addEventListener('click', function(e) {
                e.preventDefault();
                e.stopPropagation();
                
                const href = link.getAttribute('href');
                const match = href.match(/\?footnote=([^&]+)/);
                if (!match) return;
                
                const footnoteId = match[1];
                const urlParams = new URLSearchParams(window.location.search);
                const currentLang = urlParams.get('lang') || 'en';
                
                // Extract book parameter from the footnote link href (NT footnotes include &book=...)
                const hrefParams = new URLSearchParams(href.replace('?', ''));
                const linkBook = hrefParams.get('book');
                // Fall back to current page's book if not in href
                const currentBook = linkBook || urlParams.get('book') || '';
                
                const cacheKey = footnoteId + '_' + currentBook + '_' + currentLang;
                
                if (footnoteCache[cacheKey]) {
                    showFootnotePopup(footnoteId, footnoteCache[cacheKey].content, footnoteCache[cacheKey].title);
                    return;
                }
                
                // Build fetch URL with book param if available
                let fetchUrl = '/footnote/' + footnoteId + '/json/?lang=' + currentLang;
                if (currentBook) {
                    fetchUrl += '&book=' + encodeURIComponent(currentBook);
                }
                
                fetch(fetchUrl)
                    .then(response => {
                        if (!response.ok) {
                            throw new Error('Footnote not found');
                        }
                        return response.json();
                    })
                    .then(data => {
                        const title = data.title || 'Footnote ' + footnoteId;
                        const content = data.content || '<p>No content available</p>';
                        
                        const sanitizedContent = sanitizeFootnoteContent(content);
                        footnoteCache[cacheKey] = { title: title, content: sanitizedContent };
                        
                        showFootnotePopup(footnoteId, sanitizedContent, title);
                    })
                    .catch(error => {
                        console.error('Error fetching footnote:', error);
                        let fallbackUrl = '/?footnote=' + footnoteId + '&lang=' + currentLang;
                        if (currentBook) {
                            fallbackUrl += '&book=' + encodeURIComponent(currentBook);
                        }
                        window.location.href = fallbackUrl;
                    });
            });
        });
    }

    attachFootnotePopupHandlers();

    const footnotePopupObserver = new MutationObserver(attachFootnotePopupHandlers);
    footnotePopupObserver.observe(document.body, { childList: true, subtree: true });
}
