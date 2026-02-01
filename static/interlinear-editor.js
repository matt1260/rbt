/**
 * Real-time Interlinear Word Editing
 * Allows inline editing of Greek interlinear English translations
 */
(function() {
    'use strict';

    console.log('[INTERLINEAR] Script loaded at', new Date().toISOString());

    // Track currently editing element
    let currentlyEditing = null;

    // Handle click on .eng spans to make them editable
    document.addEventListener('click', function(e) {
        const engSpan = e.target.closest('.eng');
        if (!engSpan) return;

        console.log('[INTERLINEAR] Clicked on .eng span:', {
            text: engSpan.textContent,
            strongs: engSpan.dataset.strongs,
            lemma: engSpan.dataset.lemma,
            contenteditable: engSpan.getAttribute('contenteditable')
        });

        // Don't re-activate if already editing this one
        if (currentlyEditing === engSpan) return;

        // Deactivate any other editing span
        if (currentlyEditing && currentlyEditing !== engSpan) {
            deactivateEditing(currentlyEditing);
        }

        // Activate editing on this span
        activateEditing(engSpan);
    });

    // Handle clicks outside to save
    document.addEventListener('click', function(e) {
        if (currentlyEditing && !e.target.closest('.eng')) {
            console.log('[INTERLINEAR] Click outside detected, saving...');
            saveAndDeactivate(currentlyEditing);
        }
    });

    // Handle Enter key to save, Escape to cancel
    document.addEventListener('keydown', function(e) {
        if (!currentlyEditing) return;

        if (e.key === 'Enter') {
            e.preventDefault();
            console.log('[INTERLINEAR] Enter pressed, saving...');
            saveAndDeactivate(currentlyEditing);
        } else if (e.key === 'Escape') {
            e.preventDefault();
            console.log('[INTERLINEAR] Escape pressed, canceling...');
            deactivateEditing(currentlyEditing);
        }
    });

    function activateEditing(span) {
        console.log('[INTERLINEAR] Activating editing for:', span.textContent);
        span.setAttribute('contenteditable', 'true');
        span.dataset.originalText = span.textContent.trim();
        currentlyEditing = span;
        
        // Focus and select text
        span.focus();
        const range = document.createRange();
        range.selectNodeContents(span);
        const sel = window.getSelection();
        sel.removeAllRanges();
        sel.addRange(range);
    }

    function deactivateEditing(span) {
        // Restore original text if not saved
        if (span.dataset.originalText) {
            span.textContent = span.dataset.originalText;
            delete span.dataset.originalText;
        }
        span.setAttribute('contenteditable', 'false');
        if (currentlyEditing === span) {
            currentlyEditing = null;
        }
    }

    async function saveAndDeactivate(span) {
        const newText = span.textContent.trim();
        const originalText = span.dataset.originalText;

        console.log('[INTERLINEAR] Saving:', {
            newText: newText,
            originalText: originalText,
            changed: newText !== originalText
        });

        // No change, just deactivate
        if (newText === originalText || !newText) {
            console.log('[INTERLINEAR] No changes detected, deactivating');
            deactivateEditing(span);
            return;
        }

        const strongs = span.dataset.strongs;
        const lemma = span.dataset.lemma;

        console.log('[INTERLINEAR] Data attributes:', {
            strongs: strongs,
            lemma: lemma
        });

        if (!strongs || !lemma) {
            console.error('[INTERLINEAR] Missing data attributes!');
            showError(span, 'Missing data attributes');
            deactivateEditing(span);
            return;
        }

        // Show saving indicator
        showSaving(span);

        try {
            const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]').value;
            
            console.log('[INTERLINEAR] Making API call to /translate/api/update-interlinear-word/');
            
            const response = await fetch('/translate/api/update-interlinear-word/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken
                },
                body: JSON.stringify({
                    strongs: strongs,
                    lemma: lemma,
                    new_english: newText
                })
            });

            console.log('[INTERLINEAR] Response status:', response.status);

            const data = await response.json();
            
            console.log('[INTERLINEAR] Response data:', data);

            if (data.success) {
                // Update successful
                showSuccess(span, `Updated: ${data.old_english} → ${newText}`);
                delete span.dataset.originalText;
                
                // Update all other instances of this word on the page
                updateAllInstances(strongs, lemma, newText);
                
                // Show cache clear notification
                if (data.cache_cleared) {
                    console.log('[INTERLINEAR] Cache cleared - page will show updated word on next load');
                }
                
                console.log('[INTERLINEAR] Update successful!');
            } else {
                // Update failed
                console.error('[INTERLINEAR] Update failed:', data.error);
                showError(span, data.error || 'Update failed');
                deactivateEditing(span);
            }
        } catch (error) {
            console.error('[INTERLINEAR] Network error:', error);
            showError(span, 'Network error: ' + error.message);
            deactivateEditing(span);
        }

        span.setAttribute('contenteditable', 'false');
        if (currentlyEditing === span) {
            currentlyEditing = null;
        }
    }

    function updateAllInstances(strongs, lemma, newText) {
        // Find all .eng spans with matching strongs/lemma and update them
        document.querySelectorAll('.eng').forEach(function(span) {
            if (span.dataset.strongs === strongs && span.dataset.lemma === lemma) {
                span.textContent = newText;
            }
        });
    }

    function showSaving(span) {
        removeFeedback(span);
        const indicator = document.createElement('div');
        indicator.className = 'eng-save-indicator';
        indicator.textContent = 'Saving...';
        indicator.style.background = '#2196F3';
        span.style.position = 'relative';
        span.appendChild(indicator);
    }

    function showSuccess(span, message) {
        removeFeedback(span);
        const indicator = document.createElement('div');
        indicator.className = 'eng-save-indicator';
        indicator.textContent = '✓ Saved';
        span.style.position = 'relative';
        span.appendChild(indicator);

        setTimeout(function() {
            removeFeedback(span);
        }, 2000);
    }

    function showError(span, message) {
        removeFeedback(span);
        const indicator = document.createElement('div');
        indicator.className = 'eng-error-indicator';
        indicator.textContent = '✗ ' + message;
        span.style.position = 'relative';
        span.appendChild(indicator);

        setTimeout(function() {
            removeFeedback(span);
        }, 3000);
    }

    function removeFeedback(span) {
        const existing = span.querySelector('.eng-save-indicator, .eng-error-indicator');
        if (existing) {
            existing.remove();
        }
    }

    console.log('[INTERLINEAR] Real-time editing initialized');
})();
