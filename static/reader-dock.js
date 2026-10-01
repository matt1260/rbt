// Reader controls dock on chapter pages (see static/reader-dock.css). Opens and closes the
// "Reading options" panel; the toggles inside it are wired up by chapter-viewer.js.
(function () {
    'use strict';
    var STORAGE_KEY = 'rbtDockOpen';

    function isTyping(target) {
        return target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' ||
            target.tagName === 'SELECT' || target.isContentEditable);
    }

    document.addEventListener('DOMContentLoaded', function () {
        var dock = document.querySelector('.rbt-dock');
        if (!dock) return;
        var toggle = dock.querySelector('.rbt-dock__toggle');
        var panel = dock.querySelector('.rbt-dock__panel');

        function setOpen(open, remember) {
            dock.setAttribute('data-state', open ? 'open' : 'closed');
            panel.hidden = !open;
            toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
            if (remember) {
                try { localStorage.setItem(STORAGE_KEY, open ? '1' : '0'); } catch (e) { /* private mode */ }
            }
        }

        var remembered = null;
        try { remembered = localStorage.getItem(STORAGE_KEY); } catch (e) { /* private mode */ }
        // Phones start closed: an open sheet would cover the text.
        setOpen(remembered === '1' && window.innerWidth > 600, false);

        toggle.addEventListener('click', function () {
            setOpen(panel.hidden, true);
        });

        // Clicking outside, or Escape, closes the panel.
        document.addEventListener('mousedown', function (event) {
            if (!panel.hidden && !dock.contains(event.target)) setOpen(false, true);
        });
        document.addEventListener('keydown', function (event) {
            if (event.key === 'Escape' && !panel.hidden) {
                setOpen(false, true);
                toggle.focus();
            } else if (event.key === 'o' && !event.metaKey && !event.ctrlKey && !event.altKey && !isTyping(event.target)) {
                setOpen(panel.hidden, true);
            }
        });

        // The toggles are <div role="button">s that chapter-viewer.js listens to for clicks;
        // let Enter and Space press them too.
        dock.addEventListener('keydown', function (event) {
            var button = event.target.closest('[role="button"]');
            if (!button || (event.key !== 'Enter' && event.key !== ' ')) return;
            event.preventDefault();
            button.click();
        });
    });
})();
