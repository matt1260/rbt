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
            button.setAttribute('aria-pressed', on ? 'true' : 'false');
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

        button.addEventListener('keydown', function (event) {
            if (event.key !== 'Enter' && event.key !== ' ') return;
            event.preventDefault();
            show(reader.hidden, true);
        });

        document.addEventListener('keydown', function (event) {
            if (event.key !== 'r' || event.metaKey || event.ctrlKey || event.altKey || isTyping(event.target)) return;
            show(reader.hidden, true);
        });

        // Used by the Paraphrase Studio (staff) to show a newly published paraphrase without a reload.
        window.rbtReaderParaphrase = {
            setHtml: function (html) {
                reader.innerHTML = html;
            },
            show: function () {
                show(true, true);
            },
        };
    });
})();
