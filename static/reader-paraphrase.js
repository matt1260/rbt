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
    // (search/paraphrase.py). Clicking one opens the image pop-up (static/media-modal.js)
    // with that image beside its notes, read from the inert <template> holding the original
    // tooltip block. Works anywhere a .rbt-paraphrase is shown, including the staff studio's
    // previews.
    function cueItem(cue) {
        var root = cue.closest('.rbt-paraphrase');
        var template = root.querySelector('template[data-media="' + cue.getAttribute('data-media') + '"]');
        var block = template ? template.content.cloneNode(true) : null;
        var notes = block && block.querySelector('.tooltip, .tooltip2');
        return {
            media: block && block.querySelector('img, video'),
            notesHtml: notes ? notes.innerHTML : '',
            label: cue.getAttribute('aria-label') || 'Image',
            // The inline editor (staff) edits the notes of the published paraphrase's cues.
            data: {
                media: cue.getAttribute('data-media'),
                source: cue.closest('#reader-paraphrase') ? 'reader' : 'preview',
            },
        };
    }

    function modalOpen() {
        return !!(window.rbtMediaModal && window.rbtMediaModal.isOpen());
    }

    document.addEventListener('click', function (event) {
        var cue = event.target.closest && event.target.closest('.rbt-paraphrase .pp-cue');
        // In the inline editor (staff) a click selects the cue, to move or remove it.
        if (!cue || cue.closest('.ProseMirror') || !window.rbtMediaModal) return;
        event.preventDefault();
        window.rbtMediaModal.open(cueItem(cue), cue);
    });

    document.addEventListener('DOMContentLoaded', function () {
        var button = document.getElementById('paraphraseViewToggle');
        var reader = document.getElementById('reader-paraphrase');
        var verses = document.getElementById('paraphrase-area');
        if (!button || !reader || !verses) return;

        function hasContent() {
            return !reader.querySelector('.rbt-paraphrase__empty');
        }

        function apply(on, remember) {
            // The view chosen before the page painted (nt_chapter.html) is now set here.
            document.documentElement.classList.remove('rbt-start-paraphrase');
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

        // ---- Switching views ---------------------------------------------------------
        // The outgoing text blurs and dissolves while the incoming one sharpens in behind a
        // soft wipe (a view transition, styled in reader-paraphrase.css), and the toggle's
        // label decodes from scrambled glyphs. Firefox, whose view transitions drop the blur
        // and jump the scroll position, and browsers without them get the same blur out and
        // in as plain CSS animations, one after the other; reduced motion switches instantly.
        var reducedMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)');
        var useViewTransition = !!document.startViewTransition && !/\bFirefox\//.test(navigator.userAgent);
        var leaving = null;
        // The view being switched to, while a switch is still animating.
        var pendingOn = null;

        function toggle() {
            show(pendingOn !== null ? !pendingOn : reader.hidden, true);
        }

        // Swapping which text is shown must not scroll the page (browsers' scroll anchoring
        // otherwise nudges it).
        function applyKeepingScroll(on, remember) {
            var y = window.scrollY;
            document.documentElement.style.overflowAnchor = 'none';
            apply(on, remember);
            window.scrollTo(window.scrollX, y);
            document.documentElement.style.overflowAnchor = '';
        }
        var GLYPHS = 'ΑΒΓΔΘΛΞΠΣΦΨΩאבגדהוזחטמנסעפצקרשת';
        var scrambleTimer = 0;

        function scrambleLabel() {
            var label = button.querySelector('.pp-toggle__label');
            if (!label) return;
            var target = label.textContent;
            var start = performance.now();
            var duration = 420;
            // Hold the label at its final width so the glyphs don't resize the dock.
            label.style.display = 'inline-block';
            label.style.width = label.getBoundingClientRect().width + 'px';
            label.style.overflow = 'hidden';
            label.style.verticalAlign = 'bottom';
            window.cancelAnimationFrame(scrambleTimer);
            (function frame(now) {
                var settled = Math.floor(target.length * Math.min(1, (now - start) / duration));
                var text = target.slice(0, settled);
                for (var i = settled; i < target.length; i++) {
                    text += target[i] === ' ' ? ' ' : GLYPHS[Math.floor(Math.random() * GLYPHS.length)];
                }
                label.textContent = text;
                if (settled < target.length) {
                    scrambleTimer = window.requestAnimationFrame(frame);
                } else {
                    label.removeAttribute('style');
                }
            })(start);
        }

        function show(on, remember) {
            if (!remember || (reducedMotion && reducedMotion.matches)) {
                apply(on, remember);
                return;
            }
            var root = document.documentElement;
            if (useViewTransition) {
                // The two texts share a transition name only while switching, so moving
                // between chapters keeps its plain crossfade.
                root.classList.add('rbt-view-switching');
                pendingOn = on;
                var transition = document.startViewTransition(function () {
                    pendingOn = null;
                    applyKeepingScroll(on, remember);
                });
                // A transition skipped by a quicker second press is fine.
                transition.ready.catch(function () {});
                transition.finished.then(
                    function () { root.classList.remove('rbt-view-switching'); },
                    function () { root.classList.remove('rbt-view-switching'); }
                );
            } else {
                swapWithAnimations(on, remember);
            }
            scrambleLabel();
        }

        function swapWithAnimations(on, remember) {
            var outgoing = on ? verses : reader;
            var incoming = on ? reader : verses;
            if (leaving) leaving();  // a second press finishes the first switch at once
            pendingOn = on;
            var done = false;
            function onEnd(event) {
                if (event.target === outgoing) leaving();
            }
            leaving = function () {
                if (done) return;
                done = true;
                leaving = null;
                pendingOn = null;
                outgoing.removeEventListener('animationend', onEnd);
                outgoing.classList.remove('rbt-view-leave');
                applyKeepingScroll(on, remember);
                incoming.classList.remove('rbt-view-enter');
                void incoming.offsetWidth;
                incoming.classList.add('rbt-view-enter');
            };
            outgoing.addEventListener('animationend', onEnd);
            setTimeout(leaving, 300);
            outgoing.classList.add('rbt-view-leave');
        }

        var param = new URLSearchParams(window.location.search).get('view');
        var verseLink = /^#v\d+$/.test(window.location.hash) && reader.querySelector(window.location.hash);
        var wanted = param ? param === 'paraphrase' : (verseLink || readChoice() === 'paraphrase');
        show(Boolean(wanted) && (hasContent() || param === 'paraphrase'), false);
        if (verseLink && !reader.hidden) verseLink.scrollIntoView();

        button.addEventListener('click', toggle);


        document.addEventListener('keydown', function (event) {
            if (event.key !== 'r' || event.metaKey || event.ctrlKey || event.altKey || isTyping(event.target)) return;
            if (modalOpen()) return;
            toggle();
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
            // The stored notes of media item n, as saved (not the modal's display copy).
            noteHtml: function (n) {
                var template = reader.querySelector('template[data-media="' + n + '"]');
                var notes = template && template.content.querySelector('.tooltip, .tooltip2');
                return notes ? notes.innerHTML : null;
            },
            // Replace them (after an inline edit) and refresh the modal if it shows them.
            setNote: function (n, html) {
                var template = reader.querySelector('template[data-media="' + n + '"]');
                var notes = template && template.content.querySelector('.tooltip, .tooltip2');
                if (notes) notes.innerHTML = html;
                var dialog = window.rbtMediaModal && window.rbtMediaModal.dialog();
                var cue = window.rbtMediaModal && window.rbtMediaModal.opener();
                if (modalOpen() && dialog.dataset.source === 'reader' && dialog.dataset.media === String(n) && cue) {
                    window.rbtMediaModal.open(cueItem(cue), cue);
                }
            },
        };
    });
})();
