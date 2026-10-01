// "Paraphrase" reader view on NT chapter pages (search/templates/nt_chapter.html):
// switches between the verse-by-verse translation (#paraphrase-area) and the published
// AI paraphrase (#reader-paraphrase). The choice is remembered per browser; ?view=paraphrase
// or a #v12 link opens the paraphrase directly.
(function () {
    'use strict';
    var STORAGE_KEY = 'rbtReaderView';

    function readChoice() {
        try { return localStorage.getItem(STORAGE_KEY); } catch (e) { return null; }
    }

    function saveChoice(value) {
        try { localStorage.setItem(STORAGE_KEY, value); } catch (e) { /* private mode */ }
    }

    function isTyping(target) {
        return target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' ||
            target.tagName === 'SELECT' || target.isContentEditable);
    }

    // ---- Image cues ---------------------------------------------------------------
    // Each image in a paraphrase is a small round cue at the end of a sentence
    // (search/paraphrase.py). Clicking one opens a modal with that image beside its
    // notes, read from the inert <template> holding the original tooltip block.
    // Works anywhere a .rbt-paraphrase is shown, including the staff studio's previews.
    var modal = null;
    var opener = null;

    var CLOSE_ICON = '<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" focusable="false">' +
        '<path d="M6 6l12 12M18 6L6 18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>';

    function buildModal() {
        modal = document.createElement('dialog');
        modal.className = 'pp-modal';
        modal.innerHTML =
            '<div class="pp-modal__layout">' +
                '<div class="pp-modal__media"></div>' +
                '<div class="pp-modal__text"></div>' +
            '</div>' +
            '<button type="button" class="pp-modal__close" aria-label="Close">' + CLOSE_ICON + '</button>';
        // Notes in the chapter's own reading font.
        var area = document.getElementById('paraphrase-area') || document.body;
        modal.style.setProperty('--rbt-reading-font', getComputedStyle(area).fontFamily);

        modal.addEventListener('click', function (event) {
            // event.target is the dialog itself only for clicks on the backdrop.
            if (event.target === modal || event.target.closest('.pp-modal__close')) modal.close();
        });
        modal.addEventListener('keydown', function (event) {
            // Escape closes just this modal, not the staff studio underneath it.
            if (event.key === 'Escape') event.stopPropagation();
        });
        modal.addEventListener('close', function () {
            modal.querySelector('.pp-modal__media').innerHTML = ''; // stops any video
            if (opener && document.contains(opener)) opener.focus();
        });
        document.body.appendChild(modal);
    }

    // Notes usually open with a bold heading ("<b>Her Night and Day</b>. The ..."). Make it a
    // real title and drop the punctuation or line break that followed it.
    function liftTitle(box) {
        var node = box.firstChild;
        while (node && node.nodeType === 3 && !node.textContent.trim()) node = node.nextSibling;
        if (!node || node.nodeType !== 1 || !/^(B|STRONG)$/.test(node.tagName)) return;
        var title = document.createElement('h3');
        title.className = 'pp-modal__title';
        title.textContent = node.textContent.trim().replace(/[.:]+$/, '');
        var next = node.nextSibling;
        box.replaceChild(title, node);
        while (next) {
            var after = next.nextSibling;
            if (next.nodeType === 3 && /^[\s.:;,\u2014-]*$/.test(next.textContent)) {
                next.remove();
            } else if (next.nodeType === 3) {
                next.textContent = next.textContent.replace(/^[\s.:;,\u2014-]+/, '');
                break;
            } else if (next.nodeName === 'BR') {
                next.remove();
            } else {
                break;
            }
            next = after;
        }
    }

    function showImage(cue) {
        var mediaBox = modal.querySelector('.pp-modal__media');
        var textBox = modal.querySelector('.pp-modal__text');
        mediaBox.innerHTML = '';
        textBox.innerHTML = '';

        var root = cue.closest('.rbt-paraphrase');
        var template = root.querySelector('template[data-media="' + cue.getAttribute('data-media') + '"]');
        if (template) {
            var block = template.content.cloneNode(true);
            var media = block.querySelector('img, video');
            var notes = block.querySelector('.tooltip, .tooltip2');
            if (media) {
                media.removeAttribute('style');
                media.removeAttribute('width');
                media.removeAttribute('height');
                if (media.tagName === 'VIDEO') {
                    media.controls = true;
                    media.setAttribute('playsinline', '');
                }
                mediaBox.appendChild(media);
            }
            if (notes) {
                textBox.innerHTML = notes.innerHTML;
                liftTitle(textBox);
            }
        }
        modal.classList.toggle('pp-modal--no-text', !textBox.textContent.trim());
        modal.setAttribute('aria-label', cue.getAttribute('aria-label') || 'Image');
        textBox.scrollTop = 0;
    }

    document.addEventListener('click', function (event) {
        var cue = event.target.closest && event.target.closest('.rbt-paraphrase .pp-cue');
        if (!cue) return;
        event.preventDefault();
        if (!modal) buildModal();
        opener = cue;
        showImage(cue);
        if (!modal.open) modal.showModal();
    });

    document.addEventListener('DOMContentLoaded', function () {
        var button = document.getElementById('paraphraseViewToggle');
        var reader = document.getElementById('reader-paraphrase');
        var verses = document.getElementById('paraphrase-area');
        if (!button || !reader || !verses) return;

        function hasContent() {
            return !reader.querySelector('.rbt-paraphrase__empty');
        }

        function show(on, remember) {
            reader.hidden = !on;
            verses.hidden = on;
            button.classList.toggle('is-active', on);
            // The label is the action: what a click switches to.
            var label = on ? 'Read word for word' : 'Read paraphrase';
            button.innerHTML = '<i class="fas ' + (on ? 'fa-list-ol' : 'fa-book-open') + '" aria-hidden="true"></i>' +
                '<span class="pp-toggle__label">' + label + '</span>' +
                '<span class="pp-toggle__key" aria-hidden="true">R</span>';
            button.setAttribute('aria-label', label + ' (R)');
            button.title = (on ? 'You are reading the paraphrase. ' : 'You are reading the word-for-word translation. ') + label + ' (R)';
            if (remember) {
                // Replay the label's slide-in on each switch.
                button.classList.remove('is-switching');
                void button.offsetWidth;
                button.classList.add('is-switching');
            }
            document.body.classList.toggle('rbt-paraphrase-view', on);
            if (remember) saveChoice(on ? 'paraphrase' : 'verses');
        }

        var param = new URLSearchParams(window.location.search).get('view');
        var verseLink = /^#v\d+$/.test(window.location.hash) && reader.querySelector(window.location.hash);
        var wanted = param ? param === 'paraphrase' : (verseLink || readChoice() === 'paraphrase');
        show(Boolean(wanted) && (hasContent() || param === 'paraphrase'), false);
        if (verseLink && !reader.hidden) verseLink.scrollIntoView();

        button.addEventListener('click', function () {
            show(reader.hidden, true);
        });


        document.addEventListener('keydown', function (event) {
            if (event.key !== 'r' || event.metaKey || event.ctrlKey || event.altKey || isTyping(event.target)) return;
            if (modal && modal.open) return;
            show(reader.hidden, true);
        });

        // Used by the Paraphrase Studio (staff) to show a newly published paraphrase without a reload.
        window.rbtReaderParaphrase = {
            setHtml: function (html, uid, hash) {
                reader.innerHTML = html;
                // The inline editor reads these to save paragraph edits (staff only).
                if (uid) {
                    reader.dataset.uid = uid;
                    reader.dataset.hash = hash || '';
                } else {
                    delete reader.dataset.uid;
                    delete reader.dataset.hash;
                }
            },
            show: function () {
                show(true, true);
            },
        };
    });
})();
