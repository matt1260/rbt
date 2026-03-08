import { useState, useRef, useEffect, useCallback } from 'react';
import './Sanctum.css';
import {
  greekTestament,
  hebrewTestament,
  apocryphal,
  getChapterUrl,
  featuredQuotes,
  scienceArticles,
  inscriptions,
  supportedLanguages,
} from '../data/bibleBooks';
import { translations, RTL_LANGS } from '../data/translations';

const LOGO_URL = 'https://www.realbible.tech/wp-content/uploads/2022/05/rb_logo.png';
const SEARCH_URL = 'https://read.realbible.tech/search/results/';
const PAYPAL_DONATE = 'https://www.paypal.com/donate/?hosted_button_id=6LHHSLKJCY4RY';
const BTC_ADDRESS = 'bc1qcwsz2yen5f9xy7dyxma3f4wrmrck7htgwnj6al';
const RBT_HOST = 'www.realbible.tech';

/* Asset base — set by WordPress front-page.php, falls back to root */
const ASSET_BASE = (typeof window !== 'undefined' && window.__RBT_THEME_URI) || '';

/**
 * Replace realbible.tech URLs in a tr object using a slug→translatedUrl map.
 * Returns a shallow copy with updated science_articles, inscriptions, and footer URLs.
 */
function applyUrlMap(tr, urlMap) {
  if (!urlMap || Object.keys(urlMap).length === 0) return tr;

  const resolveUrl = (url) => {
    if (!url) return url;
    try {
      const u = new URL(url);
      if (u.hostname !== RBT_HOST) return url;
      // Extract slug: /some-slug/ → some-slug
      const slug = u.pathname.replace(/^\/|\/$/g, '');
      if (slug && urlMap[slug]) return urlMap[slug];
    } catch { /* not a valid URL, return as-is */ }
    return url;
  };

  const result = { ...tr };

  if (tr.science_articles) {
    result.science_articles = tr.science_articles.map((a) => ({
      ...a,
      url: resolveUrl(a.url),
    }));
  }
  if (tr.inscriptions) {
    result.inscriptions = tr.inscriptions.map((ins) => ({
      ...ins,
      url: resolveUrl(ins.url),
    }));
  }
  if (tr.footer_about_url) {
    result.footer_about_url = resolveUrl(tr.footer_about_url);
  }
  if (tr.footer_methodology_url) {
    result.footer_methodology_url = resolveUrl(tr.footer_methodology_url);
  }

  return result;
}

/* ── Hero Slides ── */
const heroSlides = [
  {
    eyebrow: 'The Real Bible Translation Project',
    title: <>Unfolding <em>the Language</em> of the Eternal One</>,
    sub: 'A translation to change the world — the Gospel of the Queen. AI translation support in 70+ languages.',
    hebrew: 'בראשית ברא אלהים את השמים ואת הארץ',
  },
  {
    eyebrow: 'The Gospel of the Queen',
    title: <>The heavenly being is <em>dual</em></>,
    sub: '"And United (\"Echud\") is making to himself a dagger, and she has twofold mouths…" — Judges 3:16 RBT',
    hebrew: 'ויעש לו אהוד חרב ולה שני פיות',
  },
  {
    eyebrow: 'Let There Be Science',
    title: <>Logos Ratio · <em>Time Symmetry</em></>,
    sub: 'If time is a closed circuit (aeon), what then? Time Symmetry, Harmonic Continuum, Unified Equilibrium, Distributed Intelligence, Self-Organization.',
    hebrew: 'יהי אור ויהי אור',
  },
  {
    eyebrow: 'The Knowledge',
    title: <>My people have been <em>destroyed</em></>,
    sub: <>From want of <span style={{ color: '#f198ba' }}>the Knowledge</span>... Hosea "Salvation" 4:6 RBT</>,
    hebrew: 'נדמו עמי מבלי הדעת',
  },
];

/* ── HTML desc renderer: string → dangerouslySetInnerHTML, else JSX ── */
function RenderDesc({ value, fallback }) {
  if (!value) return fallback;
  if (typeof value === 'string') return <p dangerouslySetInnerHTML={{ __html: value }} />;
  return <p>{value}</p>;
}

/* ── Title parser: wraps *word* in <em> ── */
function parseTitle(str) {
  if (!str) return str;
  const parts = str.split(/\*([^*]+)\*/);
  if (parts.length < 3) return str;
  return <>{parts[0]}<em>{parts[1]}</em>{parts[2]}</>;
}

/* ── Highlight helper ── */
function HighlightName({ title, highlight }) {
  if (!highlight) return title;
  const idx = title.indexOf(highlight);
  if (idx === -1) return title;
  return (
    <>
      {title.slice(0, idx)}
      <span className="hl">{highlight}</span>
      {title.slice(idx + highlight.length)}
    </>
  );
}

/* ── Book Row ── */
function BookRow({ book, lang, tr }) {
  const allChapters = Array.from({ length: book.chapters }, (_, i) => i + 1);
  const linkedSet = new Set(book.linked);
  const langParam = lang && lang !== 'en' ? `&lang=${lang}` : '';
  const bookTr = tr?.book_names?.[book.traditional];
  const displayTitle = bookTr?.title || book.title;
  const displayTraditional = bookTr?.traditional || book.traditional;

  return (
    <div className="sanctum-book-row">
      <span className="sanctum-book-name">
        <HighlightName title={displayTitle} highlight={book.highlight} />
      </span>
      <span className="sanctum-book-trad">{displayTraditional}</span>
      <div className="sanctum-chapters">
        {allChapters.map((ch) =>
          linkedSet.has(ch) ? (
            <a key={ch} className="sanctum-chapter-link" href={`${getChapterUrl(book, ch)}${langParam}`}>
              {ch}
            </a>
          ) : (
            <span key={ch} className="sanctum-chapter-num">{ch}</span>
          )
        )}
      </div>
    </div>
  );
}

/* ── Search Component ── */
function LiveSearch({ placeholder = 'Search any word, verse, or topic…' }) {
  useEffect(() => {
    const initSearch = () => {
      if (typeof window !== 'undefined' && typeof window.initRBTSearch === 'function') {
        window.initRBTSearch();
      }
    };

    initSearch();
    const rafId = requestAnimationFrame(initSearch);

    return () => cancelAnimationFrame(rafId);
  }, []);

  return (
    <div className="sanctum-search rbt-search-container">
      <form id="rbtSearchForm" action={SEARCH_URL} method="get">
        <div className="rbt-search-input-container">
          <div className="rbt-search-input-wrapper">
            <div id="rbtSearchInputField" className="rbt-search-input-field">
              <input
                id="rbtSearchInput"
                type="text"
                name="q"
                autoComplete="off"
                placeholder={placeholder}
              />
              <i className="fas fa-search rbt-input-icon rbt-search-glass" />
              <div id="rbtLiveResults" className="rbt-live-results" />
            </div>
          </div>
          <input name="scope" type="hidden" value="all" />
        </div>
      </form>
    </div>
  );
}

/* ── Language Switcher ── */
function LanguageSwitcher({ lang = 'en', panelLabel = 'Select Language' }) {
  const [open, setOpen] = useState(false);
  const panelRef = useRef(null);

  useEffect(() => {
    const handleClickOutside = (e) => {
      if (panelRef.current && !panelRef.current.contains(e.target)) {
        setOpen(false);
      }
    };
    if (open) document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [open]);

  const getLanguageUrl = (code) => code === 'en' ? '/' : `/${code}`;

  return (
    <div className="sanctum-lang-wrap" ref={panelRef}>
      <button
        className="sanctum-lang-toggle"
        onClick={() => setOpen(!open)}
        aria-label="Switch language"
        title="Switch language"
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
          <circle cx="12" cy="12" r="10" />
          <path d="M2 12h20" />
          <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" />
        </svg>
        <span>{supportedLanguages[lang]}</span>
      </button>

      {open && (
        <div className="sanctum-lang-panel">
          <div className="sanctum-lang-panel-header">
            <span>{panelLabel}</span>
            <button onClick={() => setOpen(false)} aria-label="Close">&times;</button>
          </div>
          <div className="sanctum-lang-grid">
            {Object.entries(supportedLanguages).map(([code, name]) => (
              <a
                key={code}
                href={getLanguageUrl(code)}
                className={`sanctum-lang-btn${lang === code ? ' active' : ''}`}
              >
                {name}
              </a>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

/* ── Main Component ── */
export default function Sanctum({ lang = 'en' }) {
  const rawTr = translations[lang] || translations.en;
  const isRTL = RTL_LANGS.has(lang);
  const [slide, setSlide] = useState(0);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [updateCount, setUpdateCount] = useState(null);
  const [urlMap, setUrlMap] = useState(null);
  const slideTimer = useRef(null);

  // Fetch translated URL map from WP REST API (non-English only)
  useEffect(() => {
    if (lang === 'en') return;
    fetch(`/wp-json/rbt-translator/v1/translated-urls?lang=${encodeURIComponent(lang)}`)
      .then((r) => r.ok ? r.json() : Promise.reject())
      .then((data) => setUrlMap(data))
      .catch(() => setUrlMap(null));
  }, [lang]);

  // Apply URL overrides: live translated URLs take precedence over translations.js
  const tr = (lang !== 'en' && urlMap) ? applyUrlMap(rawTr, urlMap) : rawTr;

  const nextSlide = useCallback(() => {
    setSlide((s) => (s + 1) % heroSlides.length);
  }, []);

  const prevSlide = useCallback(() => {
    setSlide((s) => (s - 1 + heroSlides.length) % heroSlides.length);
  }, []);

  useEffect(() => {
    document.body.classList.add('rbt-sanctum-ready');
    return () => {
      document.body.classList.remove('rbt-sanctum-ready');
    };
  }, []);

  // Fetch today's update count via same-origin WP proxy (avoids CORS issues)
  useEffect(() => {
    fetch('/wp-json/rbt/v1/update-count')
      .then((r) => r.ok ? r.json() : Promise.reject())
      .then((d) => setUpdateCount(d.updateCount ?? '—'))
      .catch(() => setUpdateCount('—'));
  }, []);

  // Auto-advance slider
  useEffect(() => {
    slideTimer.current = setInterval(nextSlide, 8000);
    return () => clearInterval(slideTimer.current);
  }, [nextSlide]);

  const resetTimer = () => {
    clearInterval(slideTimer.current);
    slideTimer.current = setInterval(nextSlide, 8000);
  };

  const current = heroSlides[slide];
  // Override all slides' eyebrow, title, and sub with translations
  const slidesSub = heroSlides.map((s, i) => {
    if (i === 0) return {
      ...s,
      eyebrow: tr.hero1_eyebrow || s.eyebrow,
      title: tr.hero1_title ? parseTitle(tr.hero1_title) : s.title,
      sub: tr.hero1_sub || s.sub,
    };
    if (i === 1) return {
      ...s,
      eyebrow: tr.pillar02_title || s.eyebrow,
      title: tr.hero2_title ? parseTitle(tr.hero2_title) : s.title,
      sub: tr.hero2_sub || s.sub,
    };
    if (i === 2) return {
      ...s,
      eyebrow: tr.pillar03_title || s.eyebrow,
      title: tr.hero3_title ? parseTitle(tr.hero3_title) : s.title,
      sub: tr.hero3_sub || s.sub,
    };
    return {
      ...s,
      eyebrow: tr.hero4_eyebrow || s.eyebrow,
      title: tr.hero4_title ? parseTitle(tr.hero4_title) : s.title,
      sub: tr.hero4_sub || s.sub,
    };
  });
  const currentSlide = slidesSub[slide];

  return (
    <div className="sanctum" dir={isRTL ? 'rtl' : 'ltr'}>
      {/* ── Nav ── */}
      <nav className="sanctum-nav">
        <a href="https://www.realbible.tech" className="sanctum-nav-logo">
          <img src={`${ASSET_BASE}/nun.png`} alt="nun" className="sanctum-nav-nun" />
          <span className="sanctum-nav-wordmark">Real Bible Translation Project</span>
        </a>

        <div className="sanctum-nav-right">
          <ul className={`sanctum-nav-links${mobileMenuOpen ? ' open' : ''}`}>
            <li><a href="https://read.realbible.tech/statistics/">{tr.nav_statistics}</a></li>
            <li><a href="https://www.realbible.tech/let-there-be-science/">{tr.nav_science}</a></li>
            <li><a href={tr.footer_about_url || "https://www.realbible.tech/about/"}>{tr.nav_about}</a></li>
            <li><a href={tr.footer_methodology_url || "https://www.realbible.tech/methodology/"}>{tr.nav_methodology}</a></li>
            <li><a href="#support-this-work">{tr.nav_donate}</a></li>
          </ul>

          <LanguageSwitcher lang={lang} panelLabel={tr.lang_panel} />

          <button
            className="sanctum-hamburger"
            onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
            aria-label="Toggle menu"
          >
            <span /><span /><span />
          </button>
        </div>
      </nav>

      {/* ── Hero Slider ── */}
      <section className="sanctum-hero">
        <div className="sanctum-hero-slide" key={slide}>
          <p className="sanctum-hero-eyebrow">{currentSlide.eyebrow}</p>
          <h1>{currentSlide.title}</h1>
          <p className="sanctum-hero-sub">
            {typeof currentSlide.sub === 'string'
              ? <span dangerouslySetInnerHTML={{ __html: currentSlide.sub }} />
              : currentSlide.sub}
          </p>
          <div className="sanctum-hero-hebrew">{currentSlide.hebrew}</div>
        </div>

        <LiveSearch placeholder={tr.search_placeholder} />

        <div className="sanctum-hero-actions">
          <a className="sanctum-btn-primary" href={`https://read.realbible.tech/?book=Genesis&chapter=1${lang !== 'en' ? `&lang=${lang}` : ''}`}>
            {tr.read_btn}
          </a>
          <a className="sanctum-btn-ghost" href={`https://read.realbible.tech/?book=Matthew&chapter=1${lang !== 'en' ? `&lang=${lang}` : ''}`}>
            {tr.gospels_btn}
          </a>
        </div>

        {/* Slider Controls */}
        <div className="sanctum-slider-controls">
          <button
            className="sanctum-slider-arrow"
            onClick={() => { prevSlide(); resetTimer(); }}
            aria-label="Previous slide"
          >
            ‹
          </button>
          <div className="sanctum-slider-dots">
            {heroSlides.map((_, i) => (
              <button
                key={i}
                className={`sanctum-slider-dot${i === slide ? ' active' : ''}`}
                onClick={() => { setSlide(i); resetTimer(); }}
                aria-label={`Go to slide ${i + 1}`}
              />
            ))}
          </div>
          <button
            className="sanctum-slider-arrow"
            onClick={() => { nextSlide(); resetTimer(); }}
            aria-label="Next slide"
          >
            ›
          </button>
        </div>
      </section>

      {/* ── Quote ── */}
      <section className="sanctum-quote">
        <blockquote>
          {tr.quote_text || <>
            "A queen of a south wind will awaken<br />
            within the Separation, in company with<br />
            the Generation, this one,<br />
            and she will separate down herself."
          </>}
        </blockquote>
        <cite>Matthew 12:42 RBT</cite>
      </section>

      {/* ── Three Pillars ── */}
      <section className="sanctum-pillars">
        <div className="sanctum-pillar">
          <div className="sanctum-pillar-num">01</div>
          <h3>{tr.pillar01_title}</h3>
          <RenderDesc value={tr.pillar01_desc} fallback={<>
            The Real Bible Translation Project is the unfolding of the Alignments
            (<em>Dabarim</em>) which have long been shut — mute, blind, deaf. It understands
            Hebrew not as an ancient temporal language, but a language from "the Other Side"
            to be opened in the end manifestations.
          </>} />
          <blockquote className="sanctum-pillar-quote">
            {tr.pillar01_quote || '"He has unfolded alignments of yourself; he who gives understanding is illuminating the naive ones."'}
            <cite>Psalm 119:130 RBT</cite>
          </blockquote>
          <a href="https://www.realbible.tech/notes/">{tr.notes_link}</a>
        </div>
        <div className="sanctum-pillar">
          <div className="sanctum-pillar-num">02</div>
          <h3>{tr.pillar02_title}</h3>
          <RenderDesc value={tr.pillar02_desc} fallback={<>
            Emerging from the Chaos and Night of the Sea of Existential Noise, from the unknown to the known. The sword who inverts herself. The heavenly being is <em>dual</em> — a voice from behind and in front, the logos ratio become 
            <span style={{ color: '#f198ba' }}> a flesh</span>, tenting within us. The Logos Ratio is sharper beyond any 
            <span style={{ color: '#f198ba' }}> doubled-mouthed dagger</span>. What would it mean should both sides unite?
          </>} />
          <blockquote className="sanctum-pillar-quote">
            "ויעש לו אהוד חרב ולה שני פיות"
            <br />
            {tr.pillar02_verse || '"And United ("Echud") is making to himself a dagger, and she has twofold mouths…"'}
            <cite>Judges 3:16 RBT</cite>
          </blockquote>
          <a href={`https://read.realbible.tech/?book=John&chapter=1${lang !== 'en' ? `&lang=${lang}` : ''}`}>{tr.john_link}</a>
        </div>
        <div className="sanctum-pillar">
          <div className="sanctum-pillar-num">03</div>
          <h3>{tr.pillar03_title}</h3>
          <RenderDesc value={tr.pillar03_desc} fallback={<p>Logos Ratio, Time Symmetry, Harmonic Continuum, Unified (Stable) Equilibrium, Distributed Intelligence, Self-Organization. If time is a closed circuit (aeon), what then?</p>} />
          <ul className="sanctum-pillar-links">
            {(tr.science_articles || scienceArticles).slice(0, 5).map((a) => (
              <li key={a.url}><a href={a.url}><i className="fa-brands fa-readme"></i>{a.title}</a></li>
            ))}
          </ul>
          <p><a href="https://www.realbible.tech/let-there-be-science/">{tr.explore_science}</a></p>
        </div>
      </section>

      {/* ── Current Progress ── */}
      <section className="sanctum-progress">
        <div className="sanctum-progress-inner">
          <i className="fa-regular fa-chart-bar sanctum-progress-icon"></i>
          <div>
            <h5>{tr.progress_heading}</h5>
            <p>
              {tr.progress_text}{' '}
              <span className="sanctum-progress-count">
                {updateCount === null ? <span className="sanctum-progress-loading">Loading…</span> : <a href="https://read.realbible.tech/updates/">{updateCount}</a>}
              </span>
            </p>
            <p>
              <a href="https://www.realbible.tech/server-stats/">{tr.uptime}</a>
            </p>
          </div>
        </div>
      </section>

      {/* ── Greek Testament ── */}
      <section className="sanctum-index">
        <div className="sanctum-index-header">
          <h2>{tr.section_greek}</h2>
          <span>{tr.section_greek_tag}</span>
        </div>
        {greekTestament.map((book) => (
          <BookRow key={book.traditional} book={book} lang={lang} tr={tr} />
        ))}
      </section>

      {/* ── Hebrew Testament ── */}
      <section className="sanctum-index">
        <div className="sanctum-index-header">
          <h2>{tr.section_hebrew}</h2>
          <span>{tr.section_hebrew_tag}</span>
        </div>
        {hebrewTestament.map((book) => (
          <BookRow key={book.traditional} book={book} lang={lang} tr={tr} />
        ))}

        {/* Apocryphal */}
        <div className="sanctum-apocryphal-divider">
          {apocryphal.map((book) => (
            <BookRow key={book.traditional} book={book} lang={lang} tr={tr} />
          ))}
        </div>
      </section>

      {/* ── Inscriptions ── */}
      <section className="sanctum-inscriptions">
        <h3>{tr.inscriptions_heading}</h3>
        <div className="sanctum-inscriptions-list">
          {(tr.inscriptions || inscriptions).map((ins) => (
            <a key={ins.url} href={ins.url} className="sanctum-inscription-item">
              <span>{ins.title}</span>
              <span className="sanctum-inscription-era">{ins.era}</span>
            </a>
          ))}
        </div>
      </section>

      {/* ── Articles / Science ── */}
      <section className="sanctum-articles">
        <div className="sanctum-articles-inner">
          <p className="sanctum-articles-label">{tr.pillar03_title || 'Let There Be Science'}</p>
          <h2>{tr.science_section_sub || 'Logos Ratio · Time Symmetry · Harmonic Continuum'}</h2>
          {(tr.science_articles || scienceArticles).map((article) => (
            <a key={article.url} className="sanctum-article-item" href={article.url}>
              {article.title}<span className="arrow">{isRTL ? '←' : '→'}</span>
            </a>
          ))}
        </div>
      </section>

      {/* ── Languages Grid ── */}
      <section className="sanctum-languages">
        <p className="sanctum-languages-label">{tr.languages_label}</p>
        <div className="sanctum-languages-grid">
          {Object.entries(supportedLanguages).map(([code, name]) => (
            <a 
              key={code} 
              href={code === 'en' ? '/' : `/${code}`}
              className="sanctum-language-chip"
            >
              {name}
            </a>
          ))}
        </div>
      </section>

      {/* ── Donate ── */}
      <section className="sanctum-donate" id="support-this-work">
        <div className="sanctum-donate-inner">
          <img src={`${ASSET_BASE}/nun.png`} alt="nun" className="sanctum-donate-nun" />
          <h2>{tr.support}</h2>
          <p>
            {tr.donate_desc || 'This Ancient Book has become so thoroughly corrupted by scholars and institutions that nearly every word must be carefully re-examined. It has been held hostage from the world by greed, malice, and envy. Walls around it, 2000 years thick, have been fortified at the cost of blood filling the field to the horse\'s bridle from time immemorial. Incalculable amounts of money, labor, and vigor have already been wasted. Countless, unfathomable multitudes of children have been thrown into the fires of the order of Molech, a twisted God who teaches the masses across the earth to hate their own selves until they are dead. The RBT Project is a labor of love, but it is also a monumental undertaking that requires resources to sustain in a world that is not forgiving, and would have you pay to breathe if it were possible. It is not a hobby or contribution. It is the undoing of Hell. Humans are sick. More time has never been spent on such a task. Occasionally the site may go down due to usage exceeding what I can afford. Sorry. My support base is currently 2. If you have opinions you wish to inject, I don\'t have time for that. I just want to do the work. If you want to help, donate. If you want to criticize, go somewhere else. The world is full of people who will listen to you. I am not one of them.'}
          </p>
          <div className="sanctum-donate-actions">
            <a className="sanctum-btn-primary" href={PAYPAL_DONATE}>
              {tr.donate_paypal}
            </a>
            <a className="sanctum-btn-ghost" href={`https://mempool.space/address/${BTC_ADDRESS}`}>
              {tr.donate_btc}
            </a>
          </div>
        </div>
      </section>

      {/* ── Footer ── */}
      <footer className="sanctum-footer">
        <div className="sanctum-footer-logo">Real Bible Translation</div>
        <div className="sanctum-footer-grid">
          <div className="sanctum-footer-section">
            <h4>{tr.footer_about}</h4>
            <ul className="sanctum-footer-nav">
              <li><a href={tr.footer_about_url || 'https://www.realbible.tech/about/'}>{tr.footer_about_link}</a></li>
              <li><a href={tr.footer_methodology_url || 'https://www.realbible.tech/methodology/'}>{tr.footer_methodology}</a></li>
              <li><a href="https://www.realbible.tech/copyrights/">{tr.footer_copyrights}</a></li>
            </ul>
          </div>
          <div className="sanctum-footer-section">
            <h4>{tr.footer_resources}</h4>
            <ul className="sanctum-footer-nav">
              <li><a href="https://www.realbible.tech/let-there-be-science/">{tr.footer_science}</a></li>
              <li><a href="https://read.realbible.tech/statistics/">{tr.footer_stats}</a></li>
              <li><a href="https://www.realbible.tech/notes/">{tr.footer_notes}</a></li>
            </ul>
          </div>
          <div className="sanctum-footer-section">
            <h4>{tr.footer_links}</h4>
            <ul className="sanctum-footer-nav">
              <li><a href="https://www.realbible.tech/">{tr.footer_home}</a></li>
              <li><a href="https://read.realbible.tech/search/">{tr.footer_search}</a></li>
              <li><a href="https://read.realbible.tech/updates/">{tr.footer_updates}</a></li>
            </ul>
          </div>
          <div className="sanctum-footer-section">
            <h4>Support this Work</h4>
            <ul className="sanctum-footer-nav">
              <li><a href="https://www.paypal.com/donate/?hosted_button_id=6LHHSLKJCY4RY" target="_blank" rel="noopener">Donate via PayPal</a></li>
              <li><a href="https://x.com/intent/tweet?hashtags=LetMyPeopleGo&text=Reading+the+Real+Bible+Translation+Project" target="_blank" rel="noopener">Share on X #LetMyPeopleGo</a></li>
              <li><a href="https://mempool.space/address/bc1qcwsz2yen5f9xy7dyxma3f4wrmrck7htgwnj6al" target="_blank" rel="noopener">Donate Crypto (BTC)</a></li>
            </ul>
          </div>
        </div>
        <div className="sanctum-footer-bottom" dir="ltr">
          <a href={PAYPAL_DONATE}>{tr.footer_donate}</a>
          <span>·</span>
          <span>#LetMyPeopleGo</span>
          <span>·</span>
          <span>© Now Real Bible Translation Project</span>
        </div>
      </footer>
    </div>
  );
}
