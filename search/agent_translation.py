"""
Translation by an agent instead of the Gemini API.

With settings.TRANSLATION_BACKEND == 'agent' (the default) nothing in the reader calls the
translation API: chapter jobs (TranslationJob), paraphrase translations (ChapterParaphrase
rows in a site language) and stale titles wait for an agent. The agent reaches them through
WordPress abilities (rbt-translator plugin, rbt/...), which call the private agent API in
search/views/agent_api.py; this module is what that API does:

- find work, using the background worker's own extraction, so the agent sees exactly what
  Gemini would have been sent;
- hand the agent the same instructions Gemini gets (rules, glossary, language notes);
- check what comes back (HTML intact, Hebrew/Greek untouched, nothing missing) and save it
  exactly where the worker / paraphrase thread would have.

Kinds of content: 'chapter' (verses, footnotes, the book title, Judas extras), 'paraphrase'
(a translated Reader's Paraphrase) and 'title' (titles left stale by an English rename).
Pages and posts on WordPress are the plugin's own business.

A chapter job being worked has status 'agent' (the worker only takes 'pending' and stale
'processing' jobs); a paraphrase being worked is 'running'. Any number of agents can work at
once: see "Claims" below. Claims older than CLAIM_TTL can be taken over, so a crashed agent
never strands work. Saved with publish=False, chapter
items get status DRAFT (the reader only shows 'completed') and paraphrases stay unpublished
until publish_translation.
"""
import hashlib
import logging
import re
import secrets
import uuid
from datetime import timedelta
from html.parser import HTMLParser

from django.conf import settings
from django.core.cache import cache
from django.db import connection, transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

AGENT_STATUS = 'agent'
DRAFT = 'agent_draft'
CLAIM_TTL = timedelta(hours=2)
CLAIM_MARK = 'claim:'
# A 'processing' job older than this was left by the Gemini worker, which no longer runs.
ORPHAN_AFTER = timedelta(minutes=10)
KINDS = ('chapter', 'paraphrase', 'title')
# Attribute values an agent may translate (visible or read-aloud text); every other
# attribute must come back byte-for-byte.
TRANSLATABLE_ATTRS = {'alt', 'title', 'aria-label', 'data-label'}
HEBREW = re.compile(r'[֑-״יִ-ﭏ]+')
GREEK = re.compile(r'[Ͱ-Ͽἀ-῿]+')
PLACEHOLDER = re.compile(r'\[Translation (?:unavailable|error|parsing error)|<<<(?:VERSE|FOOTNOTE)_|```')
# A language code no translation is stored under: extracting "work" for it lists every
# source item, which is how stale translations are found.
ALL_SOURCE = '__source__'


class TranslationAPIDisabled(RuntimeError):
    """Raised by the Gemini translation helpers while the agent backend is selected."""


def api_enabled():
    return getattr(settings, 'TRANSLATION_BACKEND', 'agent') != 'agent'


def require_api(what='translation'):
    if not api_enabled():
        raise TranslationAPIDisabled(
            f'The {what} API is switched off (TRANSLATION_BACKEND=agent): '
            'translations are made by the agent through the rbt/ WordPress abilities.')


# ---------------------------------------------------------------------------
# Checking a translation against its source

class _Tags(HTMLParser):
    VOID = {'img', 'br', 'hr', 'input', 'meta', 'link', 'source', 'wbr'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.seq = []

    def _attrs(self, attrs):
        return tuple(sorted((k, v) for k, v in attrs if k not in TRANSLATABLE_ATTRS))

    def handle_starttag(self, tag, attrs):
        self.seq.append(('<', tag, self._attrs(attrs)))

    def handle_startendtag(self, tag, attrs):
        self.seq.append(('<', tag, self._attrs(attrs)))

    def handle_endtag(self, tag):
        if tag not in self.VOID:
            self.seq.append(('>', tag))


def _tag_sequence(html):
    parser = _Tags()
    parser.feed(html or '')
    parser.close()
    return parser.seq


def _show(item):
    if item[0] == '>':
        return f'</{item[1]}>'
    return f'<{item[1]}' + ''.join(f' {k}="{v}"' for k, v in item[2]) + '>'


def check_translation(source, translated, language):
    """Problems with `translated` as a translation of the HTML fragment `source`; [] if fine.

    Tags and their (non-text) attributes must be unchanged and in order; Hebrew and Greek
    must come back untouched (except in the language being translated into, whose prose
    uses that script); no model placeholders or markers may be left in.
    """
    if not isinstance(translated, str) or not translated.strip():
        return ['empty translation']
    problems = []
    if PLACEHOLDER.search(translated):
        problems.append('contains a placeholder, marker or code fence')
    a, b = _tag_sequence(source), _tag_sequence(translated)
    if a != b:
        for i, (x, y) in enumerate(zip(a, b)):
            if x != y:
                problems.append(f'HTML differs at tag #{i + 1}: expected {_show(x)}, got {_show(y)}')
                break
        else:
            problems.append(f'HTML tag count differs: expected {len(a)}, got {len(b)}')
    for name, pattern, own in (('Hebrew', HEBREW, 'he'), ('Greek', GREEK, 'el')):
        if language != own and pattern.findall(source) != pattern.findall(translated):
            problems.append(f'{name} text was changed, dropped or added (copy it exactly)')
    return problems


def _check_title(text):
    if not isinstance(text, str) or not text.strip() or '<' in text or PLACEHOLDER.search(text):
        return ['must be non-empty plain text']
    return []


# ---------------------------------------------------------------------------
# Languages and instructions (the same rules Gemini is sent)

AGENT_PREAMBLE = (
    'You are translating the Real Bible Translation (RBT) into {language} ({code}). The RBT is a '
    'deliberately literal, non-traditional translation: translate THE RBT TEXT IN FRONT OF YOU, never the '
    'familiar wording of a Bible you know. Return each item under the key it was given. HTML must come back '
    'with the same tags and attributes in the same order (only text between tags, and alt/title attributes, '
    'are translated). Hebrew and Greek are copied exactly. A save that fails any check is rejected with the '
    'reasons and nothing in it is stored; run validate-translation first if unsure.\n\n'
    'When the English is ambiguous or grammatically unusual (a plural noun with a singular verb, a slash, an '
    'odd tense, a word used in an unexpected sense), consult the read-only scholarship abilities: rbt/get-verse '
    '(the Hebrew or Greek with each word\'s RBT gloss, Strong\'s number and parsing), rbt/get-lexeme and '
    'rbt/get-occurrences (how the RBT glosses that word everywhere else). Use them to understand what the RBT '
    'English means, never to replace it with the original or with a traditional reading.'
)


def list_languages():
    from search.translation_utils import SUPPORTED_LANGUAGES
    rtl = {'ar', 'he', 'fa', 'ur', 'ps', 'ku'}
    return [{'code': c, 'name': n, 'rtl': c in rtl} for c, n in SUPPORTED_LANGUAGES.items() if c != 'en']


def language_name(code):
    from search.translation_utils import SUPPORTED_LANGUAGES
    return SUPPORTED_LANGUAGES.get(code, code)


def _require_language(language):
    from search.translation_utils import SUPPORTED_LANGUAGES
    if not language or language == 'en' or language not in SUPPORTED_LANGUAGES:
        raise ValueError(f'Unsupported language: {language!r}')


def instructions(language):
    """The instruction set for each kind of item, rendered for `language`."""
    from search.translation_utils import (
        CHAPTER_PROMPT_EXAMPLES, FOOTNOTE_PROMPT_EXAMPLES, TITLE_PROMPT_GUIDANCE,
        build_glossary_section, build_language_awareness_section, build_rules_section,
    )
    glossary = build_glossary_section(language)
    return {
        'general': AGENT_PREAMBLE.format(language=language_name(language), code=language),
        'verses': '\n'.join(['Rules for verses and paraphrase paragraphs:', build_rules_section('chapter'),
                             glossary, build_language_awareness_section(language), CHAPTER_PROMPT_EXAMPLES]),
        'footnotes': '\n'.join(['Rules for footnotes and image notes:', build_rules_section('footnote'),
                                glossary, FOOTNOTE_PROMPT_EXAMPLES]),
        'titles': TITLE_PROMPT_GUIDANCE,
    }


# ---------------------------------------------------------------------------
# Chapters: what needs translating

def _extract(book, chapter, language):
    """(verses, footnotes) the worker would translate for `language` (missing ones only)."""
    from search.translation_worker import TranslationWorker
    from translate.translator import old_testament_books, new_testament_books
    worker = TranslationWorker()  # its extractors only; nothing is started
    if book == 'Joseph and Aseneth':
        return worker._extract_storehouse_content(book, chapter, language)
    if book == 'Gospel of Judas':
        return worker._extract_judas_content(book, chapter, language)
    from search.views.chapter_views_part1 import get_results
    results = get_results(book, chapter, None, 'en')
    if not results:
        raise ValueError(f'No chapter found: {book} {chapter}')
    if book == 'Genesis':
        return worker._extract_genesis_content(results, book, chapter, language)
    if book in old_testament_books:
        return worker._extract_ot_content(results, book, chapter, language)
    if book in new_testament_books:
        return worker._extract_nt_content(results, book, chapter, language)
    raise ValueError(f'Unknown book: {book}')


def _needed_titles(book, language):
    """Title rows (book title, and the Judas heading) missing or out of date in `language`."""
    from search import title_translations as titles
    from search.models import VerseTranslation
    wanted = [(book, titles.TITLE_VERSE)]
    if book == titles.JUDAS_BOOK:
        wanted.append((book, titles.JUDAS_HEADING_VERSE))
    out = {}
    for b, verse in wanted:
        row = VerseTranslation.objects.filter(
            book=b, chapter=0, verse=verse, language_code=language,
            status='completed', footnote_id__isnull=True,
        ).first()
        if not (row and titles.is_current(row)):
            out[f'{b}|{verse}'] = titles.title_source(b, verse)
    return out


def _judas_commentary(language):
    """The Judas commentary's English, if `language` still lacks it."""
    from search.db_utils import get_db_connection
    from search.models import VerseTranslation
    if VerseTranslation.objects.filter(
        book='Gospel of Judas', chapter=0, verse=2, language_code=language,
        footnote_id__isnull=True, status='completed',
    ).exists():
        return None
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute('BEGIN')
            cursor.execute('SET LOCAL search_path TO gospel_of_judas')
            cursor.execute('SELECT content FROM judas_commentary WHERE id = 1')
            row = cursor.fetchone()
    return row[0] if row and row[0] else None


def chapter_work(book, chapter, language):
    """What a chapter still needs in `language`: {'verses','footnotes','titles','extras'}.

    Missing items come from the worker's extraction; translations made from an older English
    text (a stored fingerprint that no longer matches) are included too."""
    from search.models import VerseTranslation
    from search.translation_utils import source_fingerprint
    verses, footnotes = _extract(book, chapter, language)
    verses = {int(k): v for k, v in verses.items()}
    footnotes = dict(footnotes)
    every_verse, every_note = _extract(book, chapter, ALL_SOURCE)
    stored = VerseTranslation.objects.filter(
        book=book, chapter=chapter, language_code=language, status='completed',
    ).exclude(source_hash__isnull=True).values_list('verse', 'footnote_id', 'source_hash')
    for verse, footnote_id, stored_hash in stored:
        if footnote_id:
            src = every_note.get(footnote_id)
            if src and stored_hash != source_fingerprint(src):
                footnotes[footnote_id] = src
        elif verse:
            src = every_verse.get(int(verse))
            if src and stored_hash != source_fingerprint(src):
                verses[int(verse)] = src
    extras = {}
    if book == 'Gospel of Judas':
        commentary = _judas_commentary(language)
        if commentary:
            extras['judas_commentary'] = commentary
    return {'verses': verses, 'footnotes': footnotes, 'titles': _needed_titles(book, language), 'extras': extras}


def _work_size(work):
    return sum(len(work[k]) for k in ('verses', 'footnotes', 'titles', 'extras'))


# ---------------------------------------------------------------------------
# Claims: many agents at once
#
# Every claim carries a token. A chapter job's token is kept in its error_message as
# "claim:<token>|<agent>" while its status is 'agent' (a paraphrase row's in its error
# field while 'running'); titles are claimed per language in the cache. Saving and
# releasing need the token, so an agent whose claim expired and was taken over can never
# write into someone else's work. Claiming takes row locks with SKIP LOCKED plus a
# transaction-scoped advisory lock per chapter+language, so two agents asking at the same
# moment always get different work. Saves are idempotent (a repeated save of items already
# stored with the same text succeeds), and claims accept a request_key so a claim whose
# reply was lost can be asked for again without stranding the first one.

class ClaimConflict(ValueError):
    """Someone else holds a fresh claim on this item (HTTP 409 in the agent API)."""


def _new_token():
    return secrets.token_urlsafe(18)


def _mark(token, agent):
    return f'{CLAIM_MARK}{token}|{agent}'


def _parse_mark(text):
    if text and text.startswith(CLAIM_MARK):
        token, _, agent = text[len(CLAIM_MARK):].partition('|')
        return token, agent
    return None, None


def _key_lock(*key, wait=True):
    """Transaction-scoped advisory lock on one item (Postgres); True if held."""
    if connection.vendor != 'postgresql':
        return True
    number = int(hashlib.sha1('|'.join(map(str, key)).encode('utf-8')).hexdigest()[:15], 16)
    with connection.cursor() as cursor:
        if wait:
            cursor.execute('SELECT pg_advisory_xact_lock(%s)', [number])
            return True
        cursor.execute('SELECT pg_try_advisory_xact_lock(%s)', [number])
        return bool(cursor.fetchone()[0])


def _remember(prefix, key, value):
    if key:
        cache.set(f'agent_{prefix}:{key}', value, int(CLAIM_TTL.total_seconds()))


def _recall(prefix, key):
    return cache.get(f'agent_{prefix}:{key}') if key else None


def _fresh(started_at):
    return bool(started_at) and started_at > timezone.now() - CLAIM_TTL


def _job_dict(job):
    token, holder = _parse_mark(job.error_message)
    return {
        'job_id': job.job_id, 'book': job.book, 'chapter': job.chapter, 'language': job.language_code,
        'status': job.status, 'created_at': job.created_at.isoformat() if job.created_at else None,
        'started_at': job.started_at.isoformat() if job.started_at else None,
        'verses': f'{job.translated_verses}/{job.total_verses}',
        'footnotes': f'{job.translated_footnotes}/{job.total_footnotes}',
        'claimed_by': holder if token else None,
        'error': None if token else (job.error_message or None),
    }


def _take_job(job, agent, token=None):
    """Mark a locked TranslationJob as claimed by `agent`; returns the claim token."""
    held, holder = _parse_mark(job.error_message) if job.status == AGENT_STATUS else (None, None)
    if job.status == AGENT_STATUS and _fresh(job.started_at) and held and held != token:
        raise ClaimConflict(f'{job.book} {job.chapter} ({job.language_code}) is being translated by '
                            f'{holder or "another agent"} until {(job.started_at + CLAIM_TTL):%Y-%m-%d %H:%M} UTC')
    if job.status in ('completed', 'failed'):
        job.translated_verses = job.translated_footnotes = 0
    token = held if (held and token == held) else _new_token()
    job.status, job.started_at, job.error_message = AGENT_STATUS, timezone.now(), _mark(token, agent)
    job.save()
    return token


def _chapter_candidates(language=None, limit=50):
    """Open chapter jobs in the order agents should take them, one per chapter+language:
    reader requests first, then runs nobody finished, then requests that failed under the
    API backend — skipping chapters someone is working now or a later attempt completed."""
    from django.db.models import Q
    from search.models import TranslationJob
    now = timezone.now()
    qs = TranslationJob.objects.filter(
        Q(status='pending') | Q(status='failed')
        | Q(status=AGENT_STATUS, started_at__lt=now - CLAIM_TTL)
        | Q(status='processing', started_at__lt=now - ORPHAN_AFTER))
    active = TranslationJob.objects.filter(status=AGENT_STATUS, started_at__gte=now - CLAIM_TTL)
    if language:
        qs = qs.filter(language_code=language)
        active = active.filter(language_code=language)
    busy = set(active.values_list('book', 'chapter', 'language_code'))
    done = set(TranslationJob.objects.filter(status='completed').values_list('book', 'chapter', 'language_code')
               .order_by().distinct()) if qs.filter(status='failed').exists() else set()
    rank = {'pending': 0, 'processing': 1, AGENT_STATUS: 1, 'failed': 2}
    seen, out = set(), []
    for job in sorted(qs.order_by('-created_at')[:5000], key=lambda j: (rank.get(j.status, 3), j.created_at)):
        key = (job.book, job.chapter, job.language_code)
        if key in seen or key in busy or (job.status == 'failed' and key in done):
            continue
        seen.add(key)
        out.append(job)
        if len(out) >= limit:
            break
    return out


def _claim_chapter_for(book, chapter, language, agent, token=None):
    """Claim the open job for one chapter+language (creating it if there is none)."""
    from search.models import TranslationJob
    _require_language(language)
    chapter = int(chapter)
    with transaction.atomic():
        _key_lock('chapter', book, chapter, language)
        jobs = list(TranslationJob.objects.select_for_update()
                    .filter(book=book, chapter=chapter, language_code=language)
                    .exclude(status='completed').order_by('-created_at'))
        job = next((j for j in jobs if j.status == AGENT_STATUS), None) or (jobs[0] if jobs else None)
        if job is None:
            job = TranslationJob.objects.create(job_id=str(uuid.uuid4()), book=book, chapter=chapter,
                                                language_code=language, status='pending')
        token = _take_job(job, agent, token)
    return job, token


def _claim_chapter_job(job_id, agent, token=None):
    from search.models import TranslationJob
    with transaction.atomic():
        job = TranslationJob.objects.select_for_update().filter(job_id=job_id).first()
        if not job:
            raise ValueError(f'No chapter job {job_id}')
        _key_lock('chapter', job.book, job.chapter, job.language_code)
        other = TranslationJob.objects.filter(
            book=job.book, chapter=job.chapter, language_code=job.language_code, status=AGENT_STATUS,
            started_at__gte=timezone.now() - CLAIM_TTL).exclude(pk=job.pk).first()
        if other:
            raise ClaimConflict(f'{job.book} {job.chapter} ({job.language_code}) is already being translated '
                                f'by {_parse_mark(other.error_message)[1] or "another agent"} (job {other.job_id})')
        token = _take_job(job, agent, token)
    return job, token


def _claim_next_chapter(language, agent):
    from search.models import TranslationJob
    for candidate in _chapter_candidates(language, limit=200):
        with transaction.atomic():
            job = (TranslationJob.objects.select_for_update(skip_locked=True)
                   .filter(job_id=candidate.job_id).first())
            if not job or not _key_lock('chapter', job.book, job.chapter, job.language_code, wait=False):
                continue  # another agent is taking it right now
            now = timezone.now()
            still_open = (job.status in ('pending', 'failed')
                          or (job.status == AGENT_STATUS and not _fresh(job.started_at))
                          or (job.status == 'processing' and job.started_at and job.started_at < now - ORPHAN_AFTER))
            taken = TranslationJob.objects.filter(
                book=job.book, chapter=job.chapter, language_code=job.language_code, status=AGENT_STATUS,
                started_at__gte=now - CLAIM_TTL).exclude(pk=job.pk).exists()
            if not still_open or taken:
                continue
            return job, _take_job(job, agent)
    return None, None


def _held_chapter(job_id, token):
    """The job if `token` still holds it; raises ClaimConflict otherwise."""
    from search.models import TranslationJob
    job = TranslationJob.objects.filter(job_id=job_id).first()
    if not job:
        raise ValueError(f'No chapter job {job_id}')
    held, holder = _parse_mark(job.error_message)
    if job.status != AGENT_STATUS or not token or held != token:
        raise ClaimConflict(f'You no longer hold chapter job {job_id} (it is {job.status}'
                            + (f', claimed by {holder}' if held and held != token else '')
                            + '); call get-source-content again')
    return job


# ---------------------------------------------------------------------------
# Paraphrases

def _paraphrase_dict(row):
    token, holder = _parse_mark(row.error)
    return {
        'id': row.pk, 'book': row.book, 'chapter': row.chapter, 'language': row.language_code,
        'status': row.status, 'published': row.is_published,
        'claimed_by': holder if token else None, 'error': None if token else (row.error or None),
        'created_at': row.created_at.isoformat() if getattr(row, 'created_at', None) else None,
    }


def _take_paraphrase(row, english, agent, token=None):
    from search import paraphrase
    held, holder = _parse_mark(row.error) if row.status == 'running' else (None, None)
    if row.status == 'running' and _fresh(row.started_at) and held != token:
        raise ClaimConflict(f'The {row.language_code} paraphrase of {row.book} {row.chapter} is being translated '
                            f'by {holder or "another process"}')
    token = held if (held and token == held) else _new_token()
    row.status, row.started_at, row.error = 'running', timezone.now(), _mark(token, agent)
    row.source_hash = paraphrase.html_hash(english.html)
    row.save(update_fields=['status', 'started_at', 'error', 'source_hash'])
    return token


def _claim_paraphrase(book, chapter, language, job_id, agent, token=None):
    """Claim a paraphrase translation: by id, by chapter+language (created without a Gemini
    thread if need be), or the next one waiting. Returns (row, english, token) or (None, None, None)."""
    from search import paraphrase
    from search import paraphrase_translation as pt
    from search.models import ChapterParaphrase
    base = ChapterParaphrase.objects.exclude(language_code='en')
    if job_id or book:
        with transaction.atomic():
            if job_id:
                row = base.select_for_update().filter(pk=job_id).first()
                if not row:
                    raise ValueError(f'No paraphrase job {job_id}')
                _key_lock('paraphrase', row.book, row.chapter, row.language_code)
            else:
                _require_language(language)
                chapter = int(chapter)
                _key_lock('paraphrase', book, chapter, language)
                pt.start(book, chapter, language)  # agent mode: creates the pending row, no thread
                row = (base.select_for_update().filter(book=book, chapter=chapter, language_code=language)
                       .exclude(status='done').order_by('-pk').first())
                if not row:
                    english = paraphrase.published_for(book, chapter)
                    if not english:
                        raise ValueError(f'No English paraphrase published for {book} {chapter}')
                    # Current already: retranslating on request means a fresh row.
                    row = ChapterParaphrase.objects.create(
                        batch_id=uuid.uuid4(), book=book, chapter=chapter, language_code=language,
                        provider='agent', model_name='agent', prompt_name=pt.PROMPT_NAME, created_by=pt.CREATED_BY,
                        source_hash=paraphrase.html_hash(english.html))
            english = paraphrase.published_for(row.book, row.chapter)
            if not english:
                raise ValueError(f'No English paraphrase published for {row.book} {row.chapter}')
            return row, english, _take_paraphrase(row, english, agent, token)
    now = timezone.now()
    from django.db.models import Q
    ids = list(base.filter(Q(status='pending') | Q(status='running', started_at__lt=now - CLAIM_TTL))
               .filter(**({'language_code': language} if language else {}))
               .order_by('pk').values_list('pk', flat=True)[:200])
    for pk in ids:
        with transaction.atomic():
            row = base.select_for_update(skip_locked=True).filter(pk=pk).first()
            if not row or not _key_lock('paraphrase', row.book, row.chapter, row.language_code, wait=False):
                continue
            if not (row.status == 'pending' or (row.status == 'running' and not _fresh(row.started_at))):
                continue
            english = paraphrase.published_for(row.book, row.chapter)
            if not english:
                row.status, row.error = 'failed', 'No published English paraphrase'
                row.save(update_fields=['status', 'error'])
                continue
            return row, english, _take_paraphrase(row, english, agent)
    return None, None, None


def _held_paraphrase(job_id, token):
    from search.models import ChapterParaphrase
    row = ChapterParaphrase.objects.filter(pk=job_id).exclude(language_code='en').first()
    if not row:
        raise ValueError(f'No paraphrase job {job_id}')
    held, holder = _parse_mark(row.error)
    if row.status != 'running' or not token or held != token:
        raise ClaimConflict(f'You no longer hold paraphrase job {job_id} (it is {row.status}); '
                            'call get-source-content again')
    return row


# ---------------------------------------------------------------------------
# Titles (claimed per language, in the cache)

def _title_lock_key(language):
    return f'agent_title_claim:{language}'


def _claim_titles(language, agent, token=None):
    """Claim the stale titles of one language (or of the next language nobody is doing)."""
    languages = [language] if language else sorted({i['language'] for i in stale_titles(limit=2000)})
    for lang in languages:
        key = _title_lock_key(lang)
        mine = f'{token or _new_token()}|{agent}'
        if cache.add(key, mine, int(CLAIM_TTL.total_seconds())):
            return lang, mine.split('|', 1)[0]
        held, _, holder = (cache.get(key) or '').partition('|')
        if token and held == token:
            cache.set(key, f'{token}|{agent}', int(CLAIM_TTL.total_seconds()))
            return lang, token
        if language:
            raise ClaimConflict(f'The {lang} titles are being translated by {holder or "another agent"}')
    return None, None


def _held_titles(language, token):
    held, _, holder = (cache.get(_title_lock_key(language)) or '').partition('|')
    if not token or held != token:
        raise ClaimConflict(f'You do not hold the {language} titles; call get-source-content kind=title again')


# ---------------------------------------------------------------------------
# Abilities

def get_untranslated(kind=None, language=None, limit=50):
    """Waiting work: chapter jobs and paraphrase translations nobody is doing."""
    from search.models import ChapterParaphrase
    limit = max(1, min(int(limit or 50), 500))
    out = {}
    if kind in (None, 'chapter'):
        out['chapter'] = [_job_dict(j) for j in _chapter_candidates(language, limit)]
    if kind in (None, 'paraphrase'):
        qs = ChapterParaphrase.objects.exclude(language_code='en').filter(status='pending')
        if language:
            qs = qs.filter(language_code=language)
        out['paraphrase'] = [_paraphrase_dict(r) for r in qs.order_by('pk')[:limit]]
    return out


def get_outdated(kind=None, language=None, limit=50):
    """Translations made from an older English text than the one now published."""
    from search import paraphrase
    from search.models import ChapterParaphrase, VerseTranslation
    limit = max(1, min(int(limit or 50), 500))
    out = {}
    if kind in (None, 'title'):
        out['title'] = stale_titles(language=language, limit=limit)
    if kind in (None, 'paraphrase'):
        rows = []
        qs = ChapterParaphrase.objects.exclude(language_code='en').filter(is_published=True)
        if language:
            qs = qs.filter(language_code=language)
        english_hash = {}
        for row in qs.order_by('book', 'chapter'):
            key = (row.book, row.chapter)
            if key not in english_hash:
                en = paraphrase.published_for(row.book, row.chapter)
                english_hash[key] = paraphrase.html_hash(en.html) if en else None
            if english_hash[key] and row.source_hash != english_hash[key]:
                rows.append(_paraphrase_dict(row))
                if len(rows) >= limit:
                    break
        out['paraphrase'] = rows
    if kind == 'chapter' or (kind is None and language):
        # New Testament verses are fingerprinted against new_testament.nt; one query per call.
        if not language:
            raise ValueError('get_outdated(kind="chapter") needs a language')
        from search.views.translation_views import current_nt_source_hashes
        current = current_nt_source_hashes()
        stale = {}
        for book, chapter, verse, stored in VerseTranslation.objects.filter(
            language_code=language, status='completed', footnote_id__isnull=True, chapter__gt=0,
        ).exclude(source_hash__isnull=True).values_list('book', 'chapter', 'verse', 'source_hash'):
            now_hash = current.get((book, int(chapter), int(verse)))
            if now_hash and stored != now_hash:
                stale.setdefault((book, int(chapter)), []).append(int(verse))
        out['chapter'] = [{'book': b, 'chapter': c, 'language': language, 'stale_verses': sorted(v)}
                          for (b, c), v in sorted(stale.items())[:limit]]
        out['chapter_note'] = ('New Testament verses only (they carry source fingerprints); '
                               'get_source_content also returns stale footnotes and OT verses it can detect.')
    return out


def _chapter_payload(job, token, agent):
    work = chapter_work(job.book, job.chapter, job.language_code)
    if not _work_size(work):
        _complete_chapter(job)
        return {'kind': 'chapter', 'job': _job_dict(job), 'message': 'Nothing left to translate; job completed.'}
    from search.models import TranslationJob
    TranslationJob.objects.filter(pk=job.pk).update(
        total_verses=job.translated_verses + len(work['verses']),
        total_footnotes=job.translated_footnotes + len(work['footnotes']))
    job.refresh_from_db()
    logger.info('[AGENT] %s holds chapter %s %s %s', agent, job.book, job.chapter, job.language_code)
    return {
        'kind': 'chapter', 'job': _job_dict(job), 'claim_token': token,
        'claim_expires': (job.started_at + CLAIM_TTL).isoformat(),
        'language_name': language_name(job.language_code), 'instructions': instructions(job.language_code),
        'verses': {str(k): v for k, v in sorted(work['verses'].items())},
        'footnotes': work['footnotes'], 'titles': work['titles'], 'extras': work['extras'],
        'save_with': 'save-translation kind=chapter job_id claim_token, with verses/footnotes/titles/extras under '
                     'the same keys; partial saves are fine and each save renews the claim.',
    }


def get_source_content(kind, book=None, chapter=None, language=None, job_id=None, agent='agent',
                       claim_token=None, request_key=None):
    """Claim one item and return everything needed to translate it.

    Name the item (job_id, or book+chapter+language) or leave it out to be given the next
    one waiting (optionally in `language`). Calling again with job_id + claim_token renews
    the claim and returns what is still left; repeating a call with the same request_key
    returns the claim already made instead of taking another item."""
    if kind not in KINDS:
        raise ValueError(f'kind must be one of {KINDS}')
    remembered = _recall('request', request_key)
    if remembered and remembered[0] == kind:
        job_id, claim_token = remembered[1], remembered[2]
        if kind == 'title':
            language = job_id

    if kind == 'chapter':
        if job_id:
            job, token = _claim_chapter_job(job_id, agent, claim_token)
        elif book:
            job, token = _claim_chapter_for(book, chapter, language, agent, claim_token)
        else:
            job, token = _claim_next_chapter(language, agent)
            if not job:
                return {'kind': 'chapter', 'job': None, 'message': 'No chapter jobs are waiting.'}
        _remember('request', request_key, ('chapter', job.job_id, token))
        return _chapter_payload(job, token, agent)

    if kind == 'paraphrase':
        from search import paraphrase_translation as pt
        row, english, token = _claim_paraphrase(book, chapter, language, job_id, agent, claim_token)
        if not row:
            return {'kind': 'paraphrase', 'job': None, 'message': 'No paraphrase translations are waiting.'}
        _remember('request', request_key, ('paraphrase', row.pk, token))
        notes, blocks = pt.translation_units(english.html)
        return {
            'kind': 'paraphrase', 'job': _paraphrase_dict(row), 'claim_token': token,
            'claim_expires': (row.started_at + CLAIM_TTL).isoformat(),
            'language_name': language_name(row.language_code), 'instructions': instructions(row.language_code),
            'blocks': {str(k): v for k, v in blocks.items()}, 'notes': notes,
            'save_with': 'save-translation kind=paraphrase job_id claim_token with ALL blocks (verse rules; keep every '
                         '<rbt-media n="N"> marker) and ALL notes (footnote rules) in one call.',
        }

    lang, token = _claim_titles(language, agent, claim_token)
    if not lang:
        return {'kind': 'title', 'titles': {}, 'message': 'No stale titles are waiting (or every language is taken).'}
    _remember('request', request_key, ('title', lang, token))
    items = stale_titles(language=lang, limit=500)
    return {'kind': 'title', 'language': lang, 'claim_token': token,
            'titles': {i['key']: i['english'] for i in items}, 'instructions': instructions(lang)['titles'],
            'save_with': 'save-translation kind=title language claim_token titles={"<book>|<verse>|<language>": "..."}'}


def _stored_text(book, chapter, language):
    """{('verse', n) | ('footnote', id): text} already stored, for idempotent re-saves."""
    from search.models import VerseTranslation
    out = {}
    for verse, fid, vt, ft in VerseTranslation.objects.filter(
        book=book, chapter=chapter, language_code=language, status__in=['completed', DRAFT],
    ).values_list('verse', 'footnote_id', 'verse_text', 'footnote_text'):
        out[('footnote', fid) if fid else ('verse', int(verse))] = (ft if fid else vt) or ''
    return out


def _plan_chapter(job, verses, footnotes, titles, extras):
    """(items to store, errors, items already stored with the same text)."""
    work = chapter_work(job.book, job.chapter, job.language_code)
    lang, errors, plan, already = job.language_code, [], [], 0
    stored = None
    for key, text in (verses or {}).items():
        try:
            n = int(key)
        except (TypeError, ValueError):
            errors.append(f'verse {key!r}: not a verse number'); continue
        if n not in work['verses']:
            stored = stored if stored is not None else _stored_text(job.book, job.chapter, lang)
            if stored.get(('verse', n)) == text:
                already += 1; continue
            errors.append(f'verse {n}: not awaiting translation (done already, or not in this chapter)'); continue
        errors += [f'verse {n}: {p}' for p in check_translation(work['verses'][n], text, lang)]
        plan.append(('verse', n, text, work['verses'][n]))
    for fid, text in (footnotes or {}).items():
        if fid not in work['footnotes']:
            stored = stored if stored is not None else _stored_text(job.book, job.chapter, lang)
            if stored.get(('footnote', fid)) == text:
                already += 1; continue
            errors.append(f'footnote {fid}: not awaiting translation'); continue
        errors += [f'footnote {fid}: {p}' for p in check_translation(work['footnotes'][fid], text, lang)]
        plan.append(('footnote', fid, text, work['footnotes'][fid]))
    for key, text in (titles or {}).items():
        if key not in work['titles']:
            already += 1  # current already (saved by this or an earlier call)
            continue
        errors += [f'title {key}: {p}' for p in _check_title(text)]
        plan.append(('title', key, (text or '').strip(), work['titles'][key]))
    for key, text in (extras or {}).items():
        if key not in work['extras']:
            already += 1
            continue
        errors += [f'extra {key}: {p}' for p in check_translation(work['extras'][key], text, lang)]
        plan.append(('extra', key, text, work['extras'][key]))
    if not plan and not errors and not already:
        errors.append('nothing submitted')
    return plan, errors, already


def _plan_paraphrase(row, blocks, notes):
    from search import paraphrase
    from search import paraphrase_translation as pt
    english = paraphrase.published_for(row.book, row.chapter)
    if not english or paraphrase.html_hash(english.html) != row.source_hash:
        return None, None, ['The English paraphrase changed since it was fetched; call get-source-content again']
    want_notes, want_blocks = pt.translation_units(english.html)
    blocks = {int(k): v for k, v in (blocks or {}).items()}
    notes = dict(notes or {})
    errors = [f'block {k}: missing' for k in sorted(set(want_blocks) - set(blocks))]
    errors += [f'note {k}: missing' for k in sorted(set(want_notes) - set(notes))]
    errors += [f'block {k}: not in this paraphrase' for k in sorted(set(blocks) - set(want_blocks))]
    errors += [f'note {k}: not in this paraphrase' for k in sorted(set(notes) - set(want_notes))]
    for k, text in blocks.items():
        if k in want_blocks:
            errors += [f'block {k}: {p}' for p in check_translation(want_blocks[k], text, row.language_code)]
    for k, text in notes.items():
        if k in want_notes:
            errors += [f'note {k}: {p}' for p in check_translation(want_notes[k], text, row.language_code)]
    return english, (blocks, notes), errors


def _plan_titles(titles, language=None):
    from search.models import VerseTranslation
    stale = {i['key'] for i in stale_titles(language=language, limit=2000)}
    errors, plan, already = [], [], 0
    for key, text in (titles or {}).items():
        if key not in stale:
            book, _, rest = key.rpartition('|')
            book, _, verse = book.rpartition('|')
            row = VerseTranslation.objects.filter(
                book=book, chapter=0, verse=int(verse) if verse.isdigit() else -1, language_code=rest,
                footnote_id__isnull=True).first() if book else None
            if row and (row.verse_text or '').strip() == (text or '').strip():
                already += 1; continue
            errors.append(f'{key}: not a stale title'); continue
        if language and not key.endswith(f'|{language}'):
            errors.append(f'{key}: not in the claimed language {language}'); continue
        errors += [f'{key}: {p}' for p in _check_title(text)]
        plan.append((key, (text or '').strip()))
    if not plan and not errors and not already:
        errors.append('nothing submitted')
    return plan, errors, already


def validate_translation(kind, job_id=None, verses=None, footnotes=None, titles=None, extras=None,
                         blocks=None, notes=None, language=None):
    """Run every check save_translation runs, without saving anything (no claim needed)."""
    if kind == 'chapter':
        from search.models import TranslationJob
        job = TranslationJob.objects.filter(job_id=job_id).first()
        if not job:
            raise ValueError(f'No chapter job {job_id}')
        plan, errors, already = _plan_chapter(job, verses, footnotes, titles, extras)
        return {'valid': not errors, 'items': len(plan), 'already_saved': already, 'errors': errors}
    if kind == 'paraphrase':
        from search.models import ChapterParaphrase
        row = ChapterParaphrase.objects.filter(pk=job_id).exclude(language_code='en').first()
        if not row:
            raise ValueError(f'No paraphrase job {job_id}')
        _, _, errors = _plan_paraphrase(row, blocks, notes)
        return {'valid': not errors, 'errors': errors}
    if kind == 'title':
        plan, errors, already = _plan_titles(titles, language)
        return {'valid': not errors, 'items': len(plan), 'already_saved': already, 'errors': errors}
    raise ValueError(f'kind must be one of {KINDS}')


def _complete_chapter(job):
    """Mark the job, and any other open request for the same chapter+language, completed."""
    from search.models import TranslationJob
    now = timezone.now()
    TranslationJob.objects.filter(pk=job.pk).update(status='completed', completed_at=now, error_message=None)
    TranslationJob.objects.filter(
        book=job.book, chapter=job.chapter, language_code=job.language_code,
        status__in=['pending', 'failed', 'processing'],
    ).exclude(pk=job.pk).update(status='completed', completed_at=now, error_message=None)
    job.refresh_from_db()


def save_translation(kind, job_id=None, verses=None, footnotes=None, titles=None, extras=None,
                     blocks=None, notes=None, publish=True, agent='agent', claim_token=None, language=None):
    """Check, then store, for an item this agent holds. All-or-nothing per call; repeating a
    save whose reply was lost succeeds without storing anything twice."""
    from django.db.models import F
    from search import title_translations as title_mod
    from search.models import ChapterParaphrase, TranslationJob, VerseTranslation
    from search.translation_utils import source_fingerprint
    made_by = f'agent:{agent}'[:50]
    status = 'completed' if publish else DRAFT
    replay = _recall('saved', f'{kind}:{job_id or language}:{claim_token}')

    if kind == 'chapter':
        try:
            job = _held_chapter(job_id, claim_token)
        except ClaimConflict:
            if replay:
                return replay  # the claim ended with this very save; answer as before
            raise
        plan, errors, already = _plan_chapter(job, verses, footnotes, titles, extras)
        if errors:
            return {'saved': 0, 'errors': errors}
        lang = job.language_code
        with transaction.atomic():
            for what, key, text, source in plan:
                if what == 'verse':
                    VerseTranslation.objects.update_or_create(
                        book=job.book, chapter=job.chapter, verse=key, language_code=lang, footnote_id=None,
                        defaults={'verse_text': text, 'status': status, 'generated_by': made_by,
                                  'source_hash': source_fingerprint(source)})
                elif what == 'footnote':
                    VerseTranslation.objects.update_or_create(
                        book=job.book, chapter=job.chapter, verse=0, language_code=lang, footnote_id=key,
                        defaults={'footnote_text': text, 'status': status, 'generated_by': made_by,
                                  'source_hash': source_fingerprint(source)})
                elif what == 'title':
                    book, verse = key.rsplit('|', 1)
                    title_mod.save_title(book, int(verse), lang, text)
                    VerseTranslation.objects.filter(
                        book=book, chapter=0, verse=int(verse), language_code=lang, footnote_id__isnull=True,
                    ).update(generated_by=made_by, status=status)
                elif what == 'extra' and key == 'judas_commentary':
                    VerseTranslation.objects.update_or_create(
                        book='Gospel of Judas', chapter=0, verse=2, language_code=lang, footnote_id=None,
                        defaults={'verse_text': text, 'status': status, 'generated_by': made_by,
                                  'source_hash': source_fingerprint(source)})
            TranslationJob.objects.filter(pk=job.pk).update(
                translated_verses=F('translated_verses') + sum(1 for p in plan if p[0] == 'verse'),
                translated_footnotes=F('translated_footnotes') + sum(1 for p in plan if p[0] == 'footnote'),
                started_at=timezone.now())  # saving renews the claim
        job.refresh_from_db()
        remaining = chapter_work(job.book, job.chapter, lang)
        left = _work_size(remaining)
        if not left:
            _complete_chapter(job)
        logger.info('[AGENT] %s saved %d item(s) for %s (%d left)', agent, len(plan), job_id, left)
        result = {'saved': len(plan), 'already_saved': already, 'published': publish, 'remaining': left,
                  'job': _job_dict(job), 'still_needed': {k: sorted(map(str, v)) for k, v in remaining.items() if v}}
        if not left:
            _remember('saved', f'chapter:{job_id}:{claim_token}', result)
        return result

    if kind == 'paraphrase':
        from search import paraphrase_translation as pt
        try:
            row = _held_paraphrase(job_id, claim_token)
        except ClaimConflict:
            if replay:
                return replay
            raise
        english, units, errors = _plan_paraphrase(row, blocks, notes)
        if errors:
            return {'saved': 0, 'errors': errors}
        html = pt.assemble_html(english.html, units[1], units[0])
        ChapterParaphrase.objects.filter(pk=row.pk).update(error='')
        pt.publish(row.pk, html, provider='agent', model=made_by, publish=publish)
        result = {'saved': 1, 'published': publish, 'job': _paraphrase_dict(ChapterParaphrase.objects.get(pk=row.pk))}
        _remember('saved', f'paraphrase:{job_id}:{claim_token}', result)
        return result

    if kind == 'title':
        if not language:
            raise ValueError('kind=title needs the language you claimed')
        _held_titles(language, claim_token)
        plan, errors, already = _plan_titles(titles, language)
        if errors:
            return {'saved': 0, 'errors': errors}
        with transaction.atomic():
            for key, text in plan:
                book, verse, lang = key.rsplit('|', 2)
                title_mod.save_title(book, int(verse), lang, text)
                VerseTranslation.objects.filter(
                    book=book, chapter=0, verse=int(verse), language_code=lang, footnote_id__isnull=True,
                ).update(generated_by=made_by, status=status)
        left = len(stale_titles(language=language, limit=2000))
        if not left:
            cache.delete(_title_lock_key(language))
        return {'saved': len(plan), 'already_saved': already, 'published': publish, 'remaining': left}

    raise ValueError(f'kind must be one of {KINDS}')


def release(kind, job_id=None, reason='', failed=False, claim_token=None, language=None):
    """Give a claimed item back (or mark it failed) without saving anything."""
    from search.models import ChapterParaphrase, TranslationJob
    if kind == 'chapter':
        job = _held_chapter(job_id, claim_token)
        TranslationJob.objects.filter(pk=job.pk).update(
            status='failed' if failed else 'pending', error_message=(reason or None) if failed else None)
        job.refresh_from_db()
        return _job_dict(job)
    if kind == 'paraphrase':
        row = _held_paraphrase(job_id, claim_token)
        ChapterParaphrase.objects.filter(pk=row.pk).update(
            status='failed' if failed else 'pending', error=(reason or 'released') if failed else '')
        row.refresh_from_db()
        return _paraphrase_dict(row)
    if kind == 'title':
        _held_titles(language, claim_token)
        cache.delete(_title_lock_key(language))
        return {'language': language, 'released': True}
    raise ValueError(f'kind must be one of {KINDS}')


def publish_translation(kind, book=None, chapter=None, language=None, job_id=None):
    """Make drafts saved with publish=False visible to readers."""
    from search import paraphrase_translation as pt
    from search.models import ChapterParaphrase, VerseTranslation
    if kind in ('chapter', 'title'):
        qs = VerseTranslation.objects.filter(status=DRAFT)
        if kind == 'chapter':
            _require_language(language)
            qs = qs.filter(book=book, chapter=int(chapter), language_code=language)
        else:
            qs = qs.filter(chapter=0)
            if language:
                qs = qs.filter(language_code=language)
        return {'published': qs.update(status='completed')}
    if kind == 'paraphrase':
        row = ChapterParaphrase.objects.filter(pk=job_id, status='done', is_published=False).exclude(language_code='en').first()
        if not row:
            raise ValueError(f'No unpublished paraphrase {job_id}')
        pt.publish(row.pk, row.html, provider=row.provider, model=row.model_name, publish=True)
        return {'published': 1, 'job': _paraphrase_dict(ChapterParaphrase.objects.get(pk=row.pk))}
    raise ValueError(f'kind must be one of {KINDS}')


def get_translation(kind, book=None, chapter=None, language=None):
    """What readers currently see (plus drafts) for one chapter, paraphrase or language's titles."""
    from search import paraphrase
    from search.models import VerseTranslation
    _require_language(language)
    if kind == 'chapter':
        rows = VerseTranslation.objects.filter(
            book=book, chapter=int(chapter), language_code=language, status__in=['completed', DRAFT])
        out = {'verses': {}, 'footnotes': {}, 'drafts': []}
        for r in rows.order_by('verse', 'footnote_id'):
            if r.footnote_id:
                out['footnotes'][r.footnote_id] = r.footnote_text
            else:
                out['verses'][str(r.verse)] = r.verse_text
            if r.status == DRAFT:
                out['drafts'].append(r.footnote_id or r.verse)
        title = VerseTranslation.objects.filter(
            book=book, chapter=0, verse=0, language_code=language, footnote_id__isnull=True).first()
        out['title'] = title.verse_text if title else None
        return out
    if kind == 'paraphrase':
        row = paraphrase.published_for(book, int(chapter), language)
        return {'html': row.html if row else None, 'id': row.pk if row else None}
    if kind == 'title':
        rows = VerseTranslation.objects.filter(chapter=0, language_code=language, footnote_id__isnull=True)
        return {'titles': {f'{r.book}|{r.verse}': r.verse_text for r in rows.order_by('book', 'verse')}}
    raise ValueError(f'kind must be one of {KINDS}')


def stale_titles(language=None, limit=200):
    from search import title_translations as titles
    rows = titles.stale_titles()
    if language:
        rows = [r for r in rows if r.language_code == language]
    return [{
        'key': f'{r.book}|{r.verse}|{r.language_code}', 'book': r.book, 'verse': r.verse,
        'language': r.language_code, 'english': titles.title_source(r.book, r.verse),
        'current_translation': r.verse_text,
    } for r in rows[:max(1, min(int(limit or 200), 2000))]]


# ---------------------------------------------------------------------------
# Glossary and rules

def get_glossary(language=None):
    """The terminology (with this language's required renderings) and the rule lists, as configured."""
    from search.views.translation_views import _prompt_config_payload
    config = _prompt_config_payload()
    if language:
        for term in config['glossary']:
            mine = [o for o in term['overrides'] if o['language_code'] == language]
            term['required_rendering'] = next((o['rendering'] for o in mine if o['active']), None)
            term['candidate_renderings'] = [o['rendering'] for o in mine if not o['active']]
        out = {'language': language, 'glossary': config['glossary'], 'rules': config['rules'],
               'rendered': instructions(language)}
        return out
    return config


def update_glossary(terms=None, remove=None, rules=None):
    """Add or change glossary terms (and per-language renderings) and, optionally, replace rule lists.

    terms:  [{"term", "sense", "use_guidance", "avoid"?, "active"?, "order"?,
              "overrides"?: {"<lang>": "<rendering>" | {"rendering", "status": "approved"|"candidate"}
                             | null to drop}}]
            A candidate rendering is stored but NOT sent to the translator until approved, so
            experimental equivalents can be collected and compared before they are used.
    remove: ["term", ...]
    rules:  {"chapter"|"footnote"|"both": ["rule text", ...]} — replaces those scopes only.
    """
    from search.models import PromptGlossaryTerm, PromptLanguageOverride, PromptRule
    errors = []
    for n, t in enumerate(terms or []):
        if not isinstance(t, dict) or not str(t.get('term', '')).strip():
            errors.append(f'terms[{n}] needs a "term"'); continue
        existing = PromptGlossaryTerm.objects.filter(term=t['term'].strip()).first()
        if not existing:
            for field in ('sense', 'use_guidance'):
                if not str(t.get(field, '')).strip():
                    errors.append(f'terms[{n}] ("{t["term"]}") is new and needs "{field}"')
        for lang, value in (t.get('overrides') or {}).items():
            if lang not in {x['code'] for x in list_languages()}:
                errors.append(f'terms[{n}] override for unknown language {lang!r}')
            if isinstance(value, dict) and value.get('status', 'approved') not in ('approved', 'candidate'):
                errors.append(f'terms[{n}] override {lang}: status must be "approved" or "candidate"')
    for scope, items in (rules or {}).items():
        if scope not in ('chapter', 'footnote', 'both'):
            errors.append(f'unknown rule scope {scope!r}')
        elif not isinstance(items, list) or not all(isinstance(x, str) and x.strip() for x in items):
            errors.append(f'rules[{scope!r}] must be a list of non-empty strings')
        elif not items and scope != 'both':
            errors.append(f'refusing to empty the {scope} rules')
    if errors:
        return {'saved': False, 'errors': errors}
    changed = {'terms': 0, 'removed': 0, 'rules': {}}
    with transaction.atomic():
        for t in terms or []:
            fields = {k: str(t[k]).strip() for k in ('sense', 'use_guidance', 'avoid') if k in t and t[k] is not None}
            if 'active' in t:
                fields['active'] = bool(t['active'])
            if 'order' in t:
                fields['order'] = int(t['order'])
            term, _ = PromptGlossaryTerm.objects.update_or_create(term=t['term'].strip(), defaults=fields)
            for lang, value in (t.get('overrides') or {}).items():
                rendering, status = (value.get('rendering'), value.get('status', 'approved')) \
                    if isinstance(value, dict) else (value, 'approved')
                if rendering is None or not str(rendering).strip():
                    PromptLanguageOverride.objects.filter(term=term, language_code=lang).delete()
                else:
                    PromptLanguageOverride.objects.update_or_create(
                        term=term, language_code=lang,
                        defaults={'rendering': str(rendering).strip(), 'active': status != 'candidate'})
            changed['terms'] += 1
        if remove:
            changed['removed'] = PromptGlossaryTerm.objects.filter(term__in=list(remove)).delete()[0]
        for scope, items in (rules or {}).items():
            PromptRule.objects.filter(scope=scope).delete()
            for n, text in enumerate(items, start=1):
                PromptRule.objects.create(scope=scope, order=n, text=text.strip(), active=True)
            changed['rules'][scope] = len(items)
    return {'saved': True, 'changed': changed}


# ---------------------------------------------------------------------------
# Progress

def _book_sources(book):
    """{(chapter, verse): source fingerprint} for a book whose verses are fingerprinted, else None."""
    from search.translation_utils import source_fingerprint
    if book == 'Genesis':
        from search.models import Genesis
        return {(c, v): source_fingerprint(t or '') for c, v, t in
                Genesis.objects.values_list('chapter', 'verse', 'rbt_reader')}
    from translate.translator import new_testament_books
    if book in new_testament_books:
        from search.views.translation_views import current_nt_source_hashes
        return {(c, v): h for (b, c, v), h in current_nt_source_hashes().items() if b == book}
    return None


def book_sync(book, language=None):
    """Per language, how much of a book's verse text is synchronized with the English master,
    outdated (translated from an older English text) or still untranslated."""
    from search.models import VerseTranslation
    sources = _book_sources(book)
    if sources is None:
        raise ValueError(f'Per-verse synchronization is tracked for Genesis and the New Testament, not {book!r}')
    total = len(sources)
    languages = [language] if language else [x['code'] for x in list_languages()]
    rows = VerseTranslation.objects.filter(
        book=book, language_code__in=languages, status='completed', footnote_id__isnull=True, chapter__gt=0,
    ).values_list('language_code', 'chapter', 'verse', 'source_hash')
    counts = {lang: {'synchronized': 0, 'outdated': 0} for lang in languages}
    for lang, chapter, verse, stored in rows:
        current = sources.get((int(chapter), int(verse)))
        if current is None:
            continue  # a verse no longer in the source
        # Rows saved before fingerprints existed (NULL) are trusted, as the reader does.
        counts[lang]['outdated' if stored and stored != current else 'synchronized'] += 1
    out = []
    for lang in languages:
        c = counts[lang]
        if not (c['synchronized'] or c['outdated']) and not language:
            continue  # never started; listed by get_untranslated / coverage instead
        remaining = max(0, total - c['synchronized'] - c['outdated'])
        pct = (lambda n: round(100.0 * n / total, 1) if total else 0.0)
        out.append({'language': lang, 'name': language_name(lang),
                    'synchronized_pct': pct(c['synchronized']), 'outdated_pct': pct(c['outdated']),
                    'remaining_pct': pct(remaining), **c, 'remaining': remaining})
    out.sort(key=lambda r: (-r['synchronized_pct'], r['language']))
    return {'book': book, 'source_verses': total, 'languages': out}


def get_progress(detail=False, book=None, language=None):
    """Queue state plus the translation dashboard's coverage figures; with `book`, that book's
    per-language synchronization with the English master."""
    if book:
        return book_sync(book, language)
    from django.db.models import Count
    from search import title_translations as titles
    from search.models import ChapterParaphrase, TranslationJob
    from search.views.translation_views import nt_dashboard_stats, paraphrase_coverage
    jobs = dict(TranslationJob.objects.values_list('status').annotate(n=Count('pk')).values_list('status', 'n'))
    para = dict(ChapterParaphrase.objects.exclude(language_code='en').values_list('status')
                .annotate(n=Count('pk')).values_list('status', 'n'))
    stats = nt_dashboard_stats()
    out = {
        'backend': getattr(settings, 'TRANSLATION_BACKEND', 'agent'),
        'queue': {'chapter_jobs': jobs, 'paraphrase_jobs': para, 'stale_titles': len(titles.stale_titles())},
        'new_testament': {k: v for k, v in stats.items() if k != 'books' or detail},
        'paraphrase_coverage': paraphrase_coverage(),
    }
    return out
