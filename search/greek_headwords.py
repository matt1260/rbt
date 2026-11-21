"""
The dictionary headword a New Testament interlinear word links to on Logeion.

rbt_greek.strongs_greek stores each word as it stands in the verse (κρέα), which is not what
Logeion files it under (κρέας). search/data/greek_logeion_headwords.json, made by
`manage.py build_greek_logeion_headwords`, gives the headword for each Strong's number and for the
few words that differ from their number's (a different reading, or a mis-tagged number).
"""
import json
import os
import re
from functools import lru_cache
from urllib.parse import quote

from django.conf import settings

TABLE_PATH = os.path.join(settings.BASE_DIR, 'search', 'data', 'greek_logeion_headwords.json')
LOGEION_URL = 'https://logeion.uchicago.edu/'
PERSEUS_MORPH_URL = 'https://www.perseus.tufts.edu/hopper/morph?l='


# Editorial marks that may sit on a stored word; none belongs in a dictionary lookup.
_WORD_MARKS = re.compile(r"[‹›\[\]⧼⧽〈〉«»(){}*⇔‿¦ ]")


@lru_cache(maxsize=1)
def _table():
    try:
        with open(TABLE_PATH, encoding='utf-8') as fh:
            table = json.load(fh)
    except (OSError, ValueError):
        return {}, {}
    return table.get('strongs', {}), table.get('tokens', {})


def plain_word(word):
    """The stored word without editorial marks: '‹πρὸς' -> 'πρὸς', 'μή¦γε' -> 'μήγε'."""
    return _WORD_MARKS.sub('', word or '').strip()


def logeion_headword(token_key, strongs, word):
    """Headword for the interlinear word `token_key` ('Rom.14.21-05'), else for its Strong's
    number; the plain word itself when neither is listed."""
    by_strongs, by_token = _table()
    if token_key in by_token:
        return by_token[token_key]
    try:
        number = str(int(re.sub(r'[^0-9]', '', str(strongs))))
    except ValueError:
        number = ''
    return by_strongs.get(number) or plain_word(word)


def logeion_url(headword):
    return LOGEION_URL + quote(headword or '', safe='')


def perseus_morph_url(word):
    return PERSEUS_MORPH_URL + quote(word or '', safe='')
