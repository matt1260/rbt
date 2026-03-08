document.addEventListener('DOMContentLoaded', function() {
    const switcher = document.querySelector('.language-switcher-btn');
    const dropdown = document.querySelector('.language-dropdown');
    const currentLangSpan = document.querySelector('.current-lang');
    
    if (!switcher || !dropdown) return;
    
    const langOptions = dropdown.querySelectorAll('.lang-option');

    // Function to set active language
    function setActiveLanguage(option) {
        langOptions.forEach(opt => opt.classList.remove('active')); // remove previous
        option.classList.add('active'); // add to current
        currentLangSpan.textContent = option.getAttribute('data-lang'); // update span
    }

    // Detect language from page meta/attributes (preferred), then URL path, then default to EN
    function detectPageLang() {
        // meta tag: <meta name="rbt-lang" content="es">
        const meta = document.querySelector('meta[name="rbt-lang"]');
        if (meta && meta.content) return meta.content.toLowerCase();
        // body attributes: data-rbt-lang or data-rbtLang
        const bodyLang = document.body.getAttribute('data-rbt-lang') || document.body.dataset.rbtLang;
        if (bodyLang) return bodyLang.toLowerCase();
        // any element with data-rbt-lang
        const el = document.querySelector('[data-rbt-lang]');
        if (el) return (el.getAttribute('data-rbt-lang') || '').toLowerCase();
        // fallback to html lang
        if (document.documentElement && document.documentElement.lang) return document.documentElement.lang.toLowerCase();
        return null;
    }

    const pageLang = detectPageLang();
    let activeSet = false;

    if (pageLang) {
        const optionByData = Array.from(langOptions).find(opt => (opt.getAttribute('data-lang') || '').toLowerCase() === pageLang);
        if (optionByData) {
            setActiveLanguage(optionByData);
            activeSet = true;
        }
    }

    // If not set by page lang, fall back to URL path detection
    if (!activeSet) {
        const currentPath = window.location.pathname;
        langOptions.forEach(option => {
            const href = option.getAttribute('href');
            if (currentPath === href || currentPath.startsWith(href + '/')) {
                setActiveLanguage(option);
                activeSet = true;
            }
        });
    }

    // Fallback: default to EN if nothing matches
    if (!activeSet) {
        const defaultOption = dropdown.querySelector('.lang-option[data-lang]');
        if (defaultOption) {
            // prefer an option whose data-lang is 'en' (case-insensitive)
            const enOpt = Array.from(dropdown.querySelectorAll('.lang-option')).find(o => (o.getAttribute('data-lang') || '').toLowerCase() === 'en');
            setActiveLanguage(enOpt || defaultOption);
        }
    }

    // Toggle dropdown
    switcher.addEventListener('click', function(e) {
        e.preventDefault();
        e.stopPropagation();
        const isExpanded = switcher.getAttribute('aria-expanded') === 'true';
        switcher.setAttribute('aria-expanded', !isExpanded);
        dropdown.setAttribute('aria-hidden', isExpanded);
    });

    // Close dropdown when clicking outside
    document.addEventListener('click', function(e) {
        if (!e.target.closest('.language-switcher-wrapper')) {
            switcher.setAttribute('aria-expanded', 'false');
            dropdown.setAttribute('aria-hidden', 'true');
        }
    });

    // Click handler for changing language
    langOptions.forEach(option => {
        option.addEventListener('click', function(e) {
            setActiveLanguage(this);
            switcher.setAttribute('aria-expanded', 'false');
            dropdown.setAttribute('aria-hidden', 'true');
        });
    });

    // Keyboard navigation
    switcher.addEventListener('keydown', function(e) {
        if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            switcher.click();
        }
    });
});
