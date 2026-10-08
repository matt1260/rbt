// Image pop-up and image thumbnails on chapter and verse pages (static/media-modal.css).
//
// The pop-up shows one image or video beside its notes. The paraphrase's image cues open it
// (static/reader-paraphrase.js), and so do the word-for-word text's image blocks: verse HTML
// holds each image as a .tooltip-container (the image or video, then its notes in a hidden
// .tooltip), which this file gathers into wrapping rows of captioned thumbnails.
(function () {
    'use strict';

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
            if (event.target === modal || event.target.closest('.pp-modal__close') || tapCloses(event)) modal.close();
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

    var touchScreen = window.matchMedia && window.matchMedia('(hover: none) and (pointer: coarse)');

    // On a phone or tablet a tap anywhere on the pop-up closes it, except on a link, a video
    // (its controls) or the editor's toolbar, and not in edit mode, where tapping the notes
    // edits them (staff).
    function tapCloses(event) {
        return !!(touchScreen && touchScreen.matches) &&
            !document.body.classList.contains('rbt-edit-mode') &&
            !event.target.closest('a, video, [data-rbt-ui]');
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
            if (next.nodeType === 3 && /^[\s.:;,—-]*$/.test(next.textContent)) {
                next.remove();
            } else if (next.nodeType === 3) {
                next.textContent = next.textContent.replace(/^[\s.:;,—-]+/, '');
                break;
            } else if (next.nodeName === 'BR') {
                next.remove();
            } else {
                break;
            }
            next = after;
        }
    }

    /**
     * Show one item in the pop-up: {media: <img>/<video> to show (it's moved in), notesHtml,
     * label, data: {key: value} copied onto the dialog's dataset (the staff note editor reads
     * media/source)}. `from` gets focus back when it closes.
     */
    function open(item, from) {
        if (!modal) buildModal();
        opener = from || null;
        var mediaBox = modal.querySelector('.pp-modal__media');
        var textBox = modal.querySelector('.pp-modal__text');
        mediaBox.innerHTML = '';
        textBox.innerHTML = '';
        var media = item.media;
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
        if (item.notesHtml) {
            textBox.innerHTML = item.notesHtml;
            liftTitle(textBox);
        }
        modal.classList.toggle('pp-modal--no-text', !textBox.textContent.trim());
        modal.setAttribute('aria-label', item.label || 'Image');
        delete modal.dataset.media;
        delete modal.dataset.source;
        delete modal.dataset.verse;
        delete modal.dataset.index;
        var data = item.data || {};
        for (var key in data) {
            if (Object.prototype.hasOwnProperty.call(data, key)) modal.dataset[key] = data[key];
        }
        textBox.scrollTop = 0;
        if (!modal.open) modal.showModal();
    }

    // Replace the notes the pop-up shows (after the inline editor saves them).
    function setNotes(html) {
        if (!modal) return;
        var textBox = modal.querySelector('.pp-modal__text');
        textBox.innerHTML = html || '';
        liftTitle(textBox);
        modal.classList.toggle('pp-modal--no-text', !textBox.textContent.trim());
    }

    window.rbtMediaModal = {
        open: open,
        setNotes: setNotes,
        isOpen: function () { return !!modal && modal.open; },
        dialog: function () { return modal; },
        opener: function () { return opener; },
    };

    // ---- Image blocks in the word-for-word text ---------------------------------------

    function mediaOf(container) {
        var found = container.querySelectorAll('img, video');
        for (var i = 0; i < found.length; i++) {
            if (!found[i].closest('.tooltip, .tooltip2')) return found[i];
        }
        return null;
    }

    function notesOf(container) {
        return container.querySelector('.tooltip, .tooltip2');
    }

    // The notes' bold heading, else their first sentence.
    function captionText(container) {
        var notes = notesOf(container);
        if (!notes) return '';
        var heading = notes.querySelector('b, strong');
        var text = (heading && heading.textContent.trim()) ||
            notes.textContent.trim().replace(/\s+/g, ' ').split(/(?<=[.!?])\s/)[0];
        return text.replace(/[.:]+$/, '').slice(0, 120);
    }

    function isGap(node) {
        return (node.nodeType === 3 && !node.textContent.trim()) || node.nodeName === 'BR';
    }

    function isMediaBlock(node) {
        return node && node.nodeType === 1 && node.classList.contains('tooltip-container') && !!mediaOf(node);
    }

    function decorate(container) {
        if (container.dataset.rbtThumb) return;
        container.dataset.rbtThumb = '1';
        var text = captionText(container);
        if (text) {
            var caption = document.createElement('span');
            caption.className = 'rbt-media-caption';
            caption.textContent = text;
            container.appendChild(caption);
        }
        container.setAttribute('role', 'button');
        container.setAttribute('tabindex', '0');
        container.setAttribute('aria-label', (mediaOf(container).tagName === 'VIDEO' ? 'Play video' : 'View image') +
            (text ? ': ' + text : ''));
    }

    // Each run of image blocks (only spaces or line breaks between them) becomes one row.
    function groupMedia(root) {
        var containers = root.querySelectorAll('.tooltip-container');
        for (var i = 0; i < containers.length; i++) {
            var first = containers[i];
            if (!isMediaBlock(first) || first.closest('.rbt-media-row, .ProseMirror, .tooltip, .tooltip2, .pp-modal')) continue;
            var row = document.createElement('div');
            row.className = 'rbt-media-row';
            first.parentNode.insertBefore(row, first);
            var node = first;
            while (isMediaBlock(node)) {
                var next = node.nextSibling;
                decorate(node);
                row.appendChild(node);
                // Skip the spaces and line breaks up to the next image block, if there is one.
                var probe = next;
                while (probe && isGap(probe)) probe = probe.nextSibling;
                if (!isMediaBlock(probe)) break;
                while (next !== probe) {
                    var gap = next;
                    next = next.nextSibling;
                    gap.remove();
                }
                node = probe;
            }
            // The line break that followed the last full-width image would now leave a blank line.
            var after = row.nextSibling;
            while (after && after.nodeType === 3 && !after.textContent.trim()) after = after.nextSibling;
            if (after && after.nodeName === 'BR') after.remove();
        }
    }

    // A verse's image blocks in document order (the order of its stored HTML).
    function verseMediaBlocks(verse) {
        return Array.prototype.filter.call(verse.querySelectorAll('.tooltip-container'), function (block) {
            return !block.parentElement.closest('.tooltip, .tooltip2');
        });
    }

    function itemFrom(container) {
        var media = mediaOf(container).cloneNode(true);
        var notes = notesOf(container);
        // On staff pages each verse is wrapped (.rbt-verse): the inline editor edits these
        // notes in the verse's own HTML, found by verse and position.
        var verse = container.closest('.rbt-verse[data-verse]');
        return {
            media: media,
            notesHtml: notes ? notes.innerHTML : '',
            label: container.getAttribute('aria-label') || 'Image',
            data: verse ? { source: 'verse', verse: verse.dataset.verse, index: String(verseMediaBlocks(verse).indexOf(container)) } : {},
        };
    }

    function thumbnailFor(target) {
        var container = target.closest && target.closest('.rbt-media-row .tooltip-container');
        return container && !container.closest('.ProseMirror') ? container : null;
    }

    // Capture phase, so the page's older tooltip handlers (base.html) never see the click.
    document.addEventListener('click', function (event) {
        var container = thumbnailFor(event.target);
        if (!container || event.target.closest('a')) return;
        event.preventDefault();
        event.stopPropagation();
        open(itemFrom(container), container);
    }, true);

    document.addEventListener('keydown', function (event) {
        if (event.key !== 'Enter' && event.key !== ' ') return;
        var container = thumbnailFor(event.target);
        if (!container || event.target !== container) return;
        event.preventDefault();
        open(itemFrom(container), container);
    });

    function start() {
        groupMedia(document.body);
        // Verses re-rendered later (translations arriving, the staff inline editor) get rows too.
        var pending = false;
        new MutationObserver(function (mutations) {
            if (pending) return;
            var relevant = mutations.some(function (m) {
                var el = m.target.nodeType === 1 ? m.target : m.target.parentElement;
                return !(el && el.closest && el.closest('.ProseMirror, .pp-modal, .rbt-media-row'));
            });
            if (!relevant) return;
            pending = true;
            window.requestAnimationFrame(function () {
                pending = false;
                groupMedia(document.body);
            });
        }).observe(document.body, { childList: true, subtree: true });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', start);
    } else {
        start();
    }
})();
