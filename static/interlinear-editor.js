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

    function getCsrfToken() {
        const inputToken = document.querySelector('[name=csrfmiddlewaretoken]');
        if (inputToken && inputToken.value) {
            return inputToken.value;
        }

        const cookieMatch = document.cookie.match(/(^|;\s*)csrftoken=([^;]+)/);
        return cookieMatch ? decodeURIComponent(cookieMatch[2]) : '';
    }

    async function saveAndDeactivate(span) {
        if (span.dataset.saving === '1') {
            console.log('[INTERLINEAR] Save already in progress, skipping');
            return;
        }

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
        span.dataset.saving = '1';
        span.dataset.pendingText = newText;
        span.setAttribute('contenteditable', 'false');
        showSaving(span);

        try {
            const csrfToken = getCsrfToken();
            
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
                    new_english: span.dataset.pendingText || newText
                })
            });

            console.log('[INTERLINEAR] Response status:', response.status);

            const responseText = await response.text();
            let data = null;
            if (responseText) {
                try {
                    data = JSON.parse(responseText);
                } catch (parseError) {
                    console.error('[INTERLINEAR] Response is not JSON:', responseText);
                }
            }

            if (!response.ok) {
                const statusMessage = `Server error ${response.status}`;
                const errorMessage = (data && data.error) ? data.error : statusMessage;
                showError(span, errorMessage);
                delete span.dataset.saving;
                delete span.dataset.pendingText;
                deactivateEditing(span);
                return;
            }

            console.log('[INTERLINEAR] Response data:', data);

            if (data && data.success) {
                // Update successful
                showSuccess(span, `Updated: ${data.old_english} → ${span.dataset.pendingText || newText}`);
                delete span.dataset.originalText;
                delete span.dataset.saving;
                delete span.dataset.pendingText;
                
                // Update all other instances of this word on the page
                updateAllInstances(strongs, lemma, span.dataset.pendingText || newText);
                
                // Show cache clear notification
                if (data.cache_cleared) {
                    console.log('[INTERLINEAR] Cache cleared - page will show updated word on next load');
                }
                
                console.log('[INTERLINEAR] Update successful!');
            } else {
                // Update failed
                const errorMessage = (data && data.error) ? data.error : 'Update failed';
                console.error('[INTERLINEAR] Update failed:', errorMessage);
                showError(span, errorMessage);
                delete span.dataset.saving;
                delete span.dataset.pendingText;
                deactivateEditing(span);
            }
        } catch (error) {
            console.error('[INTERLINEAR] Network error:', error);
            showError(span, 'Network error: ' + error.message);
            delete span.dataset.saving;
            delete span.dataset.pendingText;
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
        appendFeedback(span, 'eng-save-indicator', 'Saving...', '#2196F3');
    }

    function showSuccess(span, message) {
        removeFeedback(span);
        appendFeedback(span, 'eng-save-indicator', '✓ Saved', '#2E7D32');

        setTimeout(function() {
            removeFeedback(span);
        }, 2000);
    }

    function showError(span, message) {
        removeFeedback(span);
        appendFeedback(span, 'eng-error-indicator', '✗ ' + message, '#B71C1C');

        setTimeout(function() {
            removeFeedback(span);
        }, 3000);
    }

    function removeFeedback(span) {
        const feedbackId = span.dataset.feedbackId;
        if (!feedbackId || !span.parentElement) {
            return;
        }

        const existing = span.parentElement.querySelector('[data-owner="' + feedbackId + '"]');
        if (existing) {
            existing.remove();
        }
    }

    function appendFeedback(span, className, text, background) {
        if (!span.parentElement) {
            return;
        }

        if (!span.dataset.feedbackId) {
            span.dataset.feedbackId = 'eng-feedback-' + Date.now() + '-' + Math.random().toString(16).slice(2);
        }

        const indicator = document.createElement('span');
        indicator.className = className;
        indicator.textContent = text;
        indicator.dataset.owner = span.dataset.feedbackId;
        indicator.style.marginLeft = '6px';
        indicator.style.padding = '2px 6px';
        indicator.style.borderRadius = '4px';
        indicator.style.background = background;
        indicator.style.color = '#fff';
        indicator.style.fontSize = '12px';
        indicator.style.verticalAlign = 'middle';

        span.parentElement.insertBefore(indicator, span.nextSibling);
    }

    console.log('[INTERLINEAR] Real-time editing initialized');
})();
