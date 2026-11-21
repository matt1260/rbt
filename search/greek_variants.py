"""
Textual variants in the New Testament interlinear, measured against the Greek text the RBT
translates (new_testament.nt.versetext, Westcott-Hort based).

The interlinear (rbt_greek.strongs_greek) comes from BibleHub's interlinear, whose base is the
Nestle 1904 text. Words Nestle lacks are wrapped in a mark naming the latest edition that has them
(BibleHub, "Interlinear Text Sources: Methodology"):

    {TR} Textus Receptus   ⧼RP⧽ Byzantine Majority   (WH) Westcott-Hort   〈NE〉 Nestle 1904 only
    [NA] Nestle-Aland      ‹SBL› SBL Greek NT        word*  NA and SBL read another word/spelling

So a mark says nothing by itself about the RBT's text: in Acts 2:44 ‹πιστεύοντες ἦσαν› and ‹καὶ›
are SBL readings the RBT text does not have. Each verse is matched word by word against the RBT
text instead; words it lacks are faded, with a note per variant ("πιστεύοντες ἦσαν: the SBL Greek
NT reading; the RBT text has πιστεύσαντες"). Passages Westcott-Hort print in double brackets [[ ]]
(judged not part of the original text: Mark 16:9-20, John 7:53-8:11, Luke 22:43-44 ...) get a
verse note too.

`manage.py build_greek_variant_notes` writes search/data/greek_variant_notes.json from the whole
NT (verse divisions and [[ ]] passages need the neighbouring verses); pages only look it up.
"""
import difflib
import json
import os
import re
import unicodedata
from collections import Counter
from functools import lru_cache
from html import escape

from django.conf import settings

from search.seo_utils import book_to_slug

TABLE_PATH = os.path.join(settings.BASE_DIR, 'search', 'data', 'greek_variant_notes.json')

EDITION_MARKS = {          # opening mark -> edition named by BibleHub
    '{': 'the Textus Receptus',
    '⧼': 'the Byzantine Majority Text',
    '(': 'Westcott-Hort',
    '〈': 'Nestle 1904',
    '[': 'Nestle-Aland',
    '‹': 'the SBL Greek NT',
}
DOUBLE_BRACKET_NOTE = ('Westcott-Hort print this in double brackets [[ ]]: in their judgment it was '
                       'not part of the original text')
_MARKS = re.compile(r"[‹›\[\]⧼⧽〈〉«»(){}*⇔‿¦ ]")
_PUNCT = re.compile(r"[^\w\s]")
_VOWELS = set('αεηιουω')
_PREFIXES = re.compile(r'^(συ[μγλσ]|συ(?=ζ)|ε[μγ])')

# When less than this share of the RBT verse is found in the interlinear, the two are numbered
# differently (Mat 23:13-14 swap places in some editions) and word-by-word matching would mislead;
# such verses are left unmarked.
MIN_TEXT_COVERAGE = 0.6


def _strip_punct(word):
    """Punctuation and marks off, accents kept ('αὐτῷ,' -> 'αὐτῷ')."""
    return ''.join(c for c in unicodedata.normalize('NFC', _MARKS.sub('', word))
                   if not unicodedata.category(c).startswith('P'))


def _key(word):
    """Unaccented letters only, final sigma and movable nu folded: 'ἐστὶν' -> 'εστι'."""
    word = unicodedata.normalize('NFD', _MARKS.sub('', word or ''))
    word = ''.join(c for c in word if not unicodedata.combining(c))
    word = _PUNCT.sub('', word).lower().replace('ς', 'σ')
    return word[:-1] if len(word) > 3 and word.endswith('ν') else word


def _spelling(key):
    """Fold the spellings editions differ on: ει/ι, αι/ε, doubled letters, assimilated prefixes
    (Δαυείδ / Δαυίδ, κεραία / κερέα, Ἰωάννης / Ἰωάνης, συμβαλεῖν / συνβαλεῖν, ἑαυτῷ / αὑτῷ)."""
    key = _PREFIXES.sub(lambda m: 'συν' if m.group(0).startswith('συ') else 'εν', key)
    if key.startswith('εαυτ'):
        key = key[1:]
    key = key.replace('ει', 'ι').replace('αι', 'ε')
    return re.sub(r'(.)\1', r'\1', key)


def _same_word(a, b):
    """The same word spelt differently, not another form: συζητεῖν / συνζητεῖν, οὕτως / οὕτω,
    ἀπ' / ἀπό, τέσσαρα / τέσσερα are; πιστεύοντες / πιστεύσαντες, ἤκουον / ἤκουσεν are not."""
    if a == b:
        return True
    a, b = _spelling(a), _spelling(b)
    if a == b:
        return True
    short, long_ = sorted((a, b), key=len)
    if len(long_) - len(short) == 1 and long_.startswith(short) and len(short) >= 2 and (
            long_[-1] in _VOWELS or (long_[-1] == 'σ' and len(short) >= 3)):
        return True                                  # elision (ἀπ' / ἀπό), movable σ (οὕτω / οὕτως)
    if len(a) == len(b) and len(a) >= 5:
        diff = [(x, y) for x, y in zip(a, b) if x != y]
        if len(diff) == 1 and diff[0][0] in _VOWELS and diff[0][1] in _VOWELS:
            return True                              # one vowel (τέσσαρα / τέσσερα)
    return False


def _editions(words):
    """Edition named by the marks on a run of words ('the SBL Greek NT'), else None."""
    for word in words:
        for opening, edition in EDITION_MARKS.items():
            if opening in word:
                return edition
        if '*' in word:
            return 'Nestle-Aland and SBL'
    return None


def _folded(keys):
    return [_spelling(k) for k in keys]


def compare_with_rbt_text(words, rbt_text, prev_text='', next_text=''):
    """
    words: a verse's interlinear words as stored (with marks); rbt_text: the verse's Greek in the
    text the RBT translates; prev_text / next_text: the verses either side (a word the editions
    put in the next verse, Rom 7:9-10, is not a variant).
    Returns (absent, notes): absent[i] is the note for word i when the RBT text lacks it, else
    None; notes lists one line per variant in verse order.
    """
    absent = [None] * len(words)
    notes = []
    if not words:
        return absent, notes
    text_words = [w for w in (rbt_text or '').split() if _key(w)]
    if not text_words:
        # The whole verse is missing (Acts 8:37): only say so when the interlinear marks it as
        # another edition's reading, so a gap in the column is not taken for a variant.
        edition = _editions(words)
        if edition and edition != 'Westcott-Hort':
            note = f'This verse is not in the RBT Greek text; it comes from {edition}'
            return [note] * len(words), [note]
        return absent, notes

    a = [_key(w) for w in words]
    b = [_key(w) for w in text_words]
    matcher = difflib.SequenceMatcher(None, a, b, autojunk=False)
    if sum(block.size for block in matcher.get_matching_blocks()) < MIN_TEXT_COVERAGE * len(b):
        return absent, notes
    opcodes = [op for op in matcher.get_opcodes() if op[0] != 'equal']
    # Words of the RBT text left unmatched anywhere in the verse: an interlinear word found among
    # them only stands elsewhere (word order, Rom 8:14 "υἱοί εἰσιν ⇔ Θεοῦ").
    unmatched = Counter(_spelling(k) for _t, _i1, _i2, j1, j2 in opcodes for k in b[j1:j2])
    prev_keys = _folded(_key(w) for w in (prev_text or '').split() if _key(w))
    next_keys = _folded(_key(w) for w in (next_text or '').split() if _key(w))

    for tag, i1, i2, j1, j2 in opcodes:
        if tag == 'insert':
            continue                                 # RBT-text words the interlinear lacks
        ours = words[i1:i2]
        theirs = [_strip_punct(w) for w in text_words[j1:j2]]
        span = _folded(k for k in a[i1:i2] if k)     # marks alone ('⇔') carry no word
        if not span:
            continue
        if tag == 'replace' and (
                (len(ours) == len(theirs) and all(_same_word(x, y) for x, y in zip(a[i1:i2], b[j1:j2])))
                or _spelling(''.join(a[i1:i2])) == _spelling(''.join(b[j1:j2]))):
            continue                                 # spelling or word division (ὅ τι / ὅτι)
        if tag == 'delete':
            if all(unmatched[k] for k in span):
                continue                             # word order only
            if i2 == len(words) and next_keys[:len(span)] == span:
                continue                             # verse division: starts the next verse
            if i1 == 0 and span and prev_keys[-len(span):] == span:
                continue                             # verse division: ends the previous verse
        shown = ' '.join(w for w in (_strip_punct(w) for w in ours) if w.strip())
        edition = _editions(ours)
        source = f'{edition} reading' if edition else 'Nestle 1904 reading'
        if theirs:
            note = f'{shown}: {source}; the RBT text has {" ".join(theirs)}'
        else:
            note = f'{shown}: {source}; not in the RBT text'
        notes.append(note)
        for i in range(i1, i2):
            if a[i]:
                absent[i] = note
    return absent, notes


def double_bracket_verses(verses):
    """
    verses: [(verse_ref, rbt_text)] in reading order. {ref: note} for the verses whose text lies,
    wholly or in part, inside Westcott-Hort's [[ ]]; a part is quoted (Luke 24:6).
    """
    marked = {}
    inside = False
    for ref, text in verses:
        text = text or ''
        parts = []                                   # bracketed stretches of this verse
        start = 0 if inside else None
        for m in re.finditer(r'\[\[|\]\]', text):
            if m.group(0) == '[[':
                inside, start = True, m.end()
            else:
                if start is not None:
                    parts.append(text[start:m.start()])
                inside, start = False, None
        if inside and start is not None:
            parts.append(text[start:])
        if not parts:
            continue
        whole = ' '.join(parts).split() == re.sub(r'\[\[|\]\]', ' ', text).split()
        if whole:
            marked[ref] = DOUBLE_BRACKET_NOTE
        else:
            quoted = ' … '.join(' '.join(_strip_punct(w) for w in p.split() if _strip_punct(w))
                                for p in parts)
            marked[ref] = DOUBLE_BRACKET_NOTE.replace('print this', f'print “{quoted}”')
    return marked


@lru_cache(maxsize=1)
def _table():
    try:
        with open(TABLE_PATH, encoding='utf-8') as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def verse_variants(verse_ref):
    """{'notes': [...], 'words': {'04': note index}} for 'Act.2.44', or None."""
    return _table().get(verse_ref)


def compare_texts_url(book, chapter, verse):
    """BibleHub's page listing the verse in every Greek edition."""
    slug = (book_to_slug(book) or str(book).lower().replace(' ', '-')).replace('-', '_')
    return f'https://biblehub.com/texts/{slug}/{int(chapter)}-{int(verse)}.htm'


def variants_note_html(entry, book, chapter, verse):
    """The note under the interlinear for a verse with variants or a [[ ]] passage."""
    if not entry or not entry.get('notes'):
        return ''
    items = ''.join(f'<li>{escape(n)}</li>' for n in entry['notes'])
    intro = ('Faded words are not in the Greek text the RBT translates (Westcott-Hort, shown '
             'above). The interlinear follows the Nestle 1904 text, with readings from other '
             'editions.' if entry.get('words') else
             'About the Greek text of this verse:')
    return (
        '<div class="nt-variant-note">'
        f'<p>{intro}</p><ul>{items}</ul>'
        f'<a href="{compare_texts_url(book, chapter, verse)}" target="_blank" rel="noopener">'
        'Compare the Greek editions of this verse</a>'
        '</div>\n'
    )
