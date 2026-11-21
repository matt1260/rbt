"""
Build search/data/greek_logeion_headwords.json: the dictionary headword each New Testament
interlinear word (rbt_greek.strongs_greek) links to on Logeion.

The interlinear's `lemma` column holds the word as it stands in the verse (κρέα), not its
dictionary form (κρέας), so linking it straight to logeion.uchicago.edu/<word> lands on the wrong
entry or none. Three open sources decide the headword:

    MorphGNT (SBLGNT)   the lemma of each word of the verse, matched to the interlinear's words
                        by their unaccented spelling (98.5% of words match exactly)
    LSJ (Logeion's own  the headwords Logeion is certain to have; a candidate is used only when
    LSJ files)          it is one of them, so the link opens a real entry
    Abbott-Smith        the NT lexicon Logeion also carries, keyed by Strong's number; used for
                        words LSJ lacks (mostly names) and for words MorphGNT cannot match
                        (readings the SBLGNT does not have, e.g. text in ‹ ›)

Choice for one word: the MorphGNT lemma if LSJ has it, else the Abbott-Smith headword of its
Strong's number if LSJ has it, else Strong's own headword if LSJ has it, else the Abbott-Smith
headword (Logeion's NT entry). A word that is itself a headword (δεῖ, not δέω "bind") keeps it.

The file maps each Strong's number to its usual headword, plus the individual words
("Mat.1.2-03") whose headword differs from their number's. Download the sources first:

    ~/rbt_backups/lexdata/morphgnt/*-morphgnt.txt   github.com/morphgnt/sblgnt
    ~/rbt_backups/lexdata/lsj/greatscott*.xml       github.com/helmadik/LSJLogeion
    ~/rbt_backups/lexdata/abbott-smith/abbott-smith.tei.xml
                                    github.com/translatable-exegetical-tools/Abbott-Smith
    archived/strongs.sqlite (one directory above the project)   Strong's dictionary

    python manage.py build_greek_logeion_headwords [--lexdata DIR] [--audit FILE.tsv]
"""
import csv
import difflib
import glob
import json
import os
import re
import sqlite3
import unicodedata
from collections import Counter, defaultdict

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection

OUT_PATH = os.path.join(settings.BASE_DIR, 'search', 'data', 'greek_logeion_headwords.json')
STRONGS_SQLITE = os.path.join(os.path.dirname(settings.BASE_DIR), 'archived', 'strongs.sqlite')
NT_BOOKS = ('Mat Mar Luk Joh Act Rom 1Co 2Co Gal Eph Php Col 1Th 2Th 1Ti 2Ti Tit Phm Heb Jam '
            '1Pe 2Pe 1Jo 2Jo 3Jo Jud Rev').split()

# Abbott-Smith entries filed under the wrong Strong's number, or misspelt.
ABBOTT_SMITH_FIXES = {
    '1766': 'ἔνατος', '3426': 'μόδιος', '4179': 'πολλαπλασίων', '4776': 'συγκαθίζω',
    '5007': 'τάλαντον',
}
# Words whose Strong's number belongs to another word (a different reading) and which
# MorphGNT cannot match; checked by hand against the verse.
TOKEN_FIXES = {
    'Act.10.19-14': 'δύο',          # δύο tagged 5140 τρεῖς
    'Mar.14.31-03': 'ἐκπερισσῶς',   # tagged 4057 περισσῶς
    '1Co.10.28-07': 'ἱερόθυτος',    # tagged 1494 εἰδωλόθυτον
    '1Th.2.7-03': 'ἤπιος',          # tagged 3516 νήπιος
    '1Ti.1.4-08': 'ἐκζήτησις',      # tagged 2214 ζήτησις
    '1Ti.6.5-01': 'διαπαρατριβή',   # tagged 3859 παραδιατριβή
    '2Pe.2.17-06': 'ὀμίχλη',        # tagged 887 ἀχλύς (LSJ's breathing)
    'Heb.11.13-07': 'κομίζω',       # κομισάμενοι tagged 2983 λαμβάνω
    'Joh.3.28-07': 'ἐγώ',           # tagged 1510 εἰμί
    'Joh.8.10-18': 'ὁ',             # article οἱ tagged 3739 ὅς
    'Act.28.29-06': 'ὁ',            # article οἱ tagged 3739 ὅς
    '1Jo.5.7-19': 'ὁ',              # article οἱ tagged 3739 ὅς
    # MorphGNT slips
    'Joh.6.17-05': 'ἔρχομαι',       # ἤρχοντο "were going"; MorphGNT has ἄρχω
    'Act.21.6-01': 'ἀπασπάζομαι',   # MorphGNT has ἀποσπάω
    'Joh.17.6-13': 'σός',           # σοὶ ἦσαν "they were yours", tagged 4674
}
# Marks the interlinear puts around or inside words (‹ › = not in the earliest manuscripts).
WORD_MARKS = re.compile(r"[‹›\[\]⧼⧽〈〉«»(){}*⇔‿¦’'᾽ ]")


def nfc(text):
    return unicodedata.normalize('NFC', text)


def bare(text):
    """Unaccented lower-case letters only, final sigma folded: the matching key."""
    text = unicodedata.normalize('NFD', text)
    text = ''.join(c for c in text if not unicodedata.combining(c))
    return re.sub(r'[^\w]', '', text).lower().replace('ς', 'σ')


def clean_headword(word):
    """'ἄν 1' -> 'ἄν', 'ἔξεστι(ν)' -> 'ἔξεστι', 'Ἄρειος_Πάγος' -> 'Ἄρειος Πάγος'."""
    if not word:
        return None
    word = nfc(word).replace('_', ' ')
    word = re.sub(r'\([^)]*\)', '', word)
    word = re.sub(r'\s*\d+$', '', word)
    word = word.replace('̀', '́').strip()
    return word or None


def load_lsj(lexdata):
    heads = set()
    for path in glob.glob(os.path.join(lexdata, 'lsj', 'greatscott*.xml')):
        with open(path, encoding='utf-8') as fh:
            for m in re.finditer(r'<div2[^>]*>\s*<head[^>]*>(.*?)</head>', fh.read(), re.S):
                heads.add(nfc(re.sub(r'<[^>]+>', '', m.group(1)).strip()))
    return heads


def load_abbott_smith(lexdata):
    path = os.path.join(lexdata, 'abbott-smith', 'abbott-smith.tei.xml')
    by_strongs = {}
    with open(path, encoding='utf-8') as fh:
        for m in re.finditer(r'<entry n="([^"]+)"', fh.read()):
            head, *numbers = m.group(1).split('|')
            for number in numbers:
                if re.fullmatch(r'G0*\d+', number):
                    by_strongs.setdefault(str(int(number[1:])), clean_headword(head))
    by_strongs.update(ABBOTT_SMITH_FIXES)
    return by_strongs


def load_strongs():
    with sqlite3.connect(STRONGS_SQLITE) as db:
        rows = db.execute("SELECT number, lemma FROM strongs WHERE number LIKE 'G%'").fetchall()
    return {number[1:]: clean_headword(lemma) for number, lemma in rows}


def load_morphgnt(lexdata):
    verses = defaultdict(list)  # 'Mat.1.2' -> [(word, lemma)]
    for path in sorted(glob.glob(os.path.join(lexdata, 'morphgnt', '*-morphgnt.txt'))):
        with open(path, encoding='utf-8') as fh:
            for line in fh:
                bcv, _pos, _parse, _text, word, _norm, lemma = line.split()
                book, chapter, verse = int(bcv[:2]), int(bcv[2:4]), int(bcv[4:6])
                verses[f'{NT_BOOKS[book - 1]}.{chapter}.{verse}'].append((nfc(word), nfc(lemma)))
    return verses


def match_morphgnt(words, morphgnt_words):
    """{index in words: MorphGNT lemma} for the words whose spelling matches exactly."""
    a = [bare(WORD_MARKS.sub('', w or '')) for w in words]
    b = [bare(w) for w, _ in morphgnt_words]
    matched = {}
    for tag, i1, i2, j1, _j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == 'equal':
            for k in range(i2 - i1):
                matched[i1 + k] = morphgnt_words[j1 + k][1]
    return matched


class Command(BaseCommand):
    help = 'Build search/data/greek_logeion_headwords.json (NT interlinear -> Logeion headword).'

    def add_arguments(self, parser):
        parser.add_argument('--lexdata', default=os.path.expanduser('~/rbt_backups/lexdata'))
        parser.add_argument('--audit', help='Write every word and its chosen headword to this TSV.')

    def handle(self, *args, **options):
        lexdata = options['lexdata']
        lsj = load_lsj(lexdata)
        abbott_smith = load_abbott_smith(lexdata)
        strongs_dict = load_strongs()
        morphgnt = load_morphgnt(lexdata)
        if not lsj or not abbott_smith or not morphgnt:
            raise CommandError(f'Lexicon sources missing under {lexdata} (see the module docstring).')

        with connection.cursor() as cursor:
            cursor.execute('SELECT id, verse, strongs, lemma FROM rbt_greek.strongs_greek ORDER BY id')
            rows = cursor.fetchall()
        by_verse = defaultdict(list)
        for row in rows:
            by_verse[row[1].rsplit('-', 1)[0]].append(row)

        words_in = []  # (key, strongs, surface, MorphGNT lemma or None)
        for verse_ref, words in by_verse.items():
            matched = match_morphgnt([w[3] for w in words], morphgnt.get(verse_ref, []))
            for i, (_id, key, strongs, surface) in enumerate(words):
                words_in.append((key, str(int(strongs)), surface, clean_headword(matched.get(i))))

        # What the matched words of each Strong's number resolve to, for its unmatched words.
        matched_lsj = defaultdict(Counter)
        for _key, strongs, _surface, mg in words_in:
            if mg and mg in lsj:
                matched_lsj[strongs][mg] += 1

        chosen = {}   # token key -> (strongs, headword, source)
        audit = []
        stats = Counter()
        for key, strongs, surface, mg in words_in:
            ab = abbott_smith.get(strongs)
            st = strongs_dict.get(strongs)
            surface_key = bare(WORD_MARKS.sub('', surface or ''))
            if key in TOKEN_FIXES:
                headword, source = TOKEN_FIXES[key], 'hand'
            elif mg and ab and bare(ab) == surface_key != bare(mg) and ab in lsj:
                headword, source = ab, 'word-is-headword'      # δεῖ, not δέω "bind"
            elif mg and mg in lsj:
                headword, source = mg, 'morphgnt+lsj'
            elif not mg and matched_lsj[strongs]:
                headword, source = matched_lsj[strongs].most_common(1)[0][0], 'same-strongs'
            elif ab and ab in lsj:
                headword, source = ab, 'abbott-smith+lsj'
            elif st and st in lsj:
                headword, source = st, 'strongs+lsj'
            elif ab:
                headword, source = ab, 'abbott-smith'
                if mg and bare(mg) == bare(ab) and mg[:1].isupper() and ab[:1].islower():
                    headword = mg                               # φῆστος -> Φῆστος
            else:
                headword, source = mg or st, 'morphgnt' if mg else 'strongs'
            stats[source] += 1
            chosen[key] = (strongs, headword, source)
            audit.append((key, strongs, surface, mg or '', ab or '', st or '', headword, source,
                          '' if mg else 'unmatched'))

        per_strongs = defaultdict(Counter)
        for strongs, headword, _source in chosen.values():
            per_strongs[strongs][headword] += 1
        default = {s: c.most_common(1)[0][0] for s, c in per_strongs.items()}
        tokens = {k: h for k, (s, h, _src) in chosen.items() if h != default[s]}
        table = {
            'strongs': dict(sorted(default.items(), key=lambda kv: int(kv[0]))),
            'tokens': dict(sorted(tokens.items())),
        }
        with open(OUT_PATH, 'w', encoding='utf-8') as fh:
            json.dump(table, fh, ensure_ascii=False, indent=0, sort_keys=False)
            fh.write('\n')

        if options.get('audit'):
            with open(options['audit'], 'w', encoding='utf-8', newline='') as fh:
                writer = csv.writer(fh, delimiter='\t')
                writer.writerow(['token', 'strongs', 'word', 'morphgnt', 'abbott_smith', 'strongs_hw',
                                 'headword', 'source', 'note'])
                writer.writerows(audit)

        self.stdout.write(f'{len(rows)} words, {len(default)} Strong\'s numbers, '
                          f'{len(tokens)} word-level exceptions -> {OUT_PATH}')
        for source, n in stats.most_common():
            self.stdout.write(f'  {source:18} {n}')
