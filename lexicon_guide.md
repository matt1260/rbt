# Hebrew-Greek Lexicon Guide

A PostgreSQL-based lexicon derived from the CATSS parallel alignment corpus, providing Hebrew stem ↔ Greek translation correspondences with Strong's number integration.

## Quick Start

**Primary Use Case: Strong's → LXX Translations**

```python
from db.lexicon import Lexicon

lex = Lexicon()

# Get LXX translations for a Strong's number
for heb, grk, freq, pct in lex.strongs_to_greek("H3068"):
    print(f"{heb} → {grk}: {freq} ({pct}%)")
# Output: יהוה → κυριοσ: 5509 (76.3%)
```

---

## Connection

```python
import psycopg

conn = psycopg.connect(dbname="rbt", user="matt")
cur = conn.cursor()
cur.execute("SET search_path TO catss")
```

Or via command line:
```bash
psql -d rbt -U matt -c "SET search_path TO catss; <query>"
```

---

## Schema Overview

### Core Tables

| Table | Rows | Description |
|-------|------|-------------|
| `alignment_group` | 293,971 | Verse-level alignment units (Hebrew ↔ Greek) |
| `hebrew_token` | 376,175 | Hebrew word forms with surface text |
| `hebrew_segment` | 539,342 | Morphological segments (prefix/stem/suffix) |
| `greek_token` | 540,419 | Greek word forms with normalization |
| `hebrew_stem_class` | 26,869 | Hebrew stem → POS classification |
| `greek_lemma` | 20,274 | Greek form → lemma mappings |

### Bridge Tables (Strong's Integration)

| Table | Rows | Description |
|-------|------|-------------|
| `hebrew_lemma_strongs` | 41,250 | Hebrew lemma → Strong's number (from ETCBC) |
| `hebrew_stem_to_lemma` | 18,469 | CATSS stem → ETCBC lemma mapping (71% coverage) |
| `strongs_lxx_profile` | 72,324 | Strong's → Greek translation frequencies |

**Coverage**: 3,906 unique Strong's numbers, 9,894 Hebrew lemmas, 23,845 Greek lemmas

### Views & Materialized Views

| View | Description |
|------|-------------|
| `clean_hebrew_stems` | Filtered stems (≥3 chars, Hebrew only, no pronominal suffixes) |
| `stem_greek_cooccurrence` | Raw Hebrew stem ↔ Greek form co-occurrence counts |
| `stem_greek_lemma_cooccurrence` | Hebrew stem ↔ Greek lemma co-occurrence counts |
| `stem_greek_cooccurrence_enriched` | Co-occurrences with Hebrew POS classification |

---

## Table Schemas

### `alignment_group`
```sql
group_id TEXT PRIMARY KEY  -- Format: "BOOK.chapter.verse.seq" (e.g., "GEN.1.1.001")
```

### `hebrew_token`
```sql
id          TEXT PRIMARY KEY  -- Format: "h_000001"
group_id    TEXT NOT NULL     -- FK → alignment_group
surface     TEXT NOT NULL     -- Hebrew text (may contain "/" for morpheme boundaries)
token_order INTEGER           -- Position within alignment group
```

### `hebrew_segment`
```sql
id            SERIAL PRIMARY KEY
token_id      TEXT NOT NULL     -- FK → hebrew_token
segment_type  TEXT              -- 'prefix' | 'stem' | 'suffix'
value         TEXT NOT NULL     -- The segment text (e.g., "ב", "ראשׁית")
segment_order INTEGER           -- Order within token
```

**Prefixes** (closed set): ב, ה, ו, כ, ל, מ  
**Suffixes** (closed set): ה, ו, ם, ן, י, ך

### `greek_token`
```sql
id          TEXT PRIMARY KEY  -- Format: "g_000001"
group_id    TEXT NOT NULL     -- FK → alignment_group
surface     TEXT NOT NULL     -- Greek text with diacritics (e.g., "ἀρχῇ")
token_order INTEGER           -- Position within alignment group
normalized  TEXT              -- Lowercase, no diacritics (e.g., "αρχη")
token_type  TEXT              -- 'content' | 'article' | 'conjunction' | 'preposition'
```

### `hebrew_stem_class`
```sql
stem TEXT PRIMARY KEY         -- Hebrew stem (e.g., "אמר")
pos  TEXT                     -- 'noun' | 'verb' | 'proper' | 'pronoun' | 'demonstrative'
```

### `greek_lemma`
```sql
form  TEXT PRIMARY KEY        -- Normalized form (e.g., "λεγω")
lemma TEXT NOT NULL           -- Dictionary lemma (e.g., "λεγω")
```

### `hebrew_lemma_strongs`
```sql
hebrew_lemma TEXT PRIMARY KEY -- ETCBC lemma (e.g., "יהוה")
strongs      TEXT NOT NULL    -- Strong's number without H prefix (e.g., "3068")
```

### `hebrew_stem_to_lemma`
```sql
stem  TEXT PRIMARY KEY        -- CATSS stem (e.g., "יאמר")
lemma TEXT NOT NULL           -- ETCBC lemma (e.g., "אמר")
```

### `strongs_lxx_profile`
```sql
strongs        TEXT NOT NULL      -- Strong's number with H prefix (e.g., "H3068")
hebrew_lemma   TEXT NOT NULL      -- Hebrew lemma (e.g., "יהוה")
greek_lemma    TEXT NOT NULL      -- Greek lemma (e.g., "κυριοσ")
frequency      INTEGER NOT NULL   -- Co-occurrence count
proportion_pct NUMERIC(5,1)       -- Percentage of this translation for this lemma
PRIMARY KEY (strongs, greek_lemma)
```

---

## Common Queries

### 1. Get LXX translations for a Strong's number (PRIMARY USE CASE)

```sql
SELECT strongs, hebrew_lemma, greek_lemma, frequency, proportion_pct
FROM strongs_lxx_profile
WHERE strongs = 'H3068'  -- יהוה (YHWH)
ORDER BY frequency DESC
LIMIT 10;
```

Result:
| strongs | hebrew_lemma | greek_lemma | frequency | proportion_pct |
|---------|--------------|-------------|-----------|----------------|
| H3068 | יהוה | κυριοσ | 5509 | 76.3 |
| H3068 | יהוה | θεοσ | 247 | 3.4 |

### 2. Find Hebrew stems for a Greek lemma

```sql
SELECT hebrew_stem, freq
FROM stem_greek_lemma_cooccurrence
WHERE greek_lemma = 'κυριοσ'
ORDER BY freq DESC
LIMIT 10;
```

Result:
| hebrew_stem | freq |
|-------------|------|
| יהוה | 5509 |
| אדני | 386 |

### 3. Get Hebrew stem with POS classification

```sql
SELECT hebrew_stem, hebrew_pos, greek_lemma, freq
FROM stem_greek_cooccurrence_enriched
WHERE hebrew_stem = 'מלכ'
ORDER BY freq DESC;
```

### 4. Find all verbs aligned with a Greek verb

```sql
SELECT hebrew_stem, greek_lemma, freq
FROM stem_greek_cooccurrence_enriched
WHERE hebrew_pos = 'verb'
  AND greek_lemma = 'ειμι'
ORDER BY freq DESC;
```

### 5. Reconstruct a Hebrew token from segments

```sql
SELECT 
    ht.id,
    ht.surface,
    string_agg(hs.value, '' ORDER BY hs.segment_order) AS reconstructed
FROM hebrew_token ht
JOIN hebrew_segment hs ON hs.token_id = ht.id
WHERE ht.id = 'h_000001'
GROUP BY ht.id, ht.surface;
```

### 6. Get alignment for a specific verse

```sql
SELECT 
    ag.group_id,
    ht.surface AS hebrew,
    gt.surface AS greek
FROM alignment_group ag
JOIN hebrew_token ht ON ht.group_id = ag.group_id
JOIN greek_token gt ON gt.group_id = ag.group_id
WHERE ag.group_id LIKE 'GEN.1.1.%'
ORDER BY ag.group_id, ht.token_order;
```

### 7. Top noun correspondences

```sql
SELECT hebrew_stem, greek_lemma, freq
FROM stem_greek_cooccurrence_enriched
WHERE hebrew_pos = 'noun'
ORDER BY freq DESC
LIMIT 20;
```

### 8. Search by Greek normalized form (ignoring diacritics)

```sql
SELECT gt.surface, gt.normalized, gl.lemma
FROM greek_token gt
LEFT JOIN greek_lemma gl ON gt.normalized = gl.form
WHERE gt.normalized = 'θεοσ'
LIMIT 5;
```

---

## Python API

The `db/lexicon.py` module provides a high-level API:

```python
from db.lexicon import Lexicon

lex = Lexicon()

# PRIMARY: Strong's number → LXX translations
for heb, grk, freq, pct in lex.strongs_to_greek("H3068"):
    print(f"{heb} → {grk}: {freq} ({pct}%)")

# Reverse lookup: Greek → Hebrew stems  
for stem, freq in lex.greek_to_hebrew("κυριοσ"):
    print(f"{stem}: {freq}")

# CATSS stem → ETCBC lemma
lemma = lex.stem_to_lemma("יאמר")  # → "אמר"

# Get Strong's for a lemma
strongs = lex.get_strongs("יהוה")  # → "3068"

# Get POS classification
pos = lex.get_pos("מלכ")  # → "noun"

# Search stems by pattern
stems = lex.search_hebrew("מל%", pos="noun")
```

### Command-Line Interface

```bash
# Primary: Strong's → LXX
python db/lexicon.py --strongs H3068

# Greek → Hebrew stems
python db/lexicon.py --greek κυριοσ

# Hebrew stem full info
python db/lexicon.py אמר
```

---

## Data Statistics

### Bridge Table Coverage
| Table | Unique Items | Coverage |
|-------|--------------|----------|
| Strong's numbers | 3,906 | Full OT coverage |
| Hebrew lemmas | 9,894 | From ETCBC |
| CATSS stems mapped | 18,469 | 71% of stems |
| Greek lemmas | 23,845 | From stem co-occurrences |

### Hebrew Stem POS Distribution
| POS | Stems | % |
|-----|-------|---|
| noun | 18,874 | 70.2% |
| verb | 7,932 | 29.5% |
| proper | 43 | 0.2% |
| pronoun | 15 | 0.1% |
| demonstrative | 5 | 0.0% |

### Greek Token Type Distribution
| Type | Count | % |
|------|-------|---|
| content | 403,405 | 74.6% |
| conjunction | 56,160 | 10.4% |
| article | 54,601 | 10.1% |
| preposition | 26,253 | 4.9% |

---

## Refreshing Materialized Views

After any data changes, refresh the materialized views:

```sql
SET search_path TO catss;
REFRESH MATERIALIZED VIEW stem_greek_cooccurrence;
REFRESH MATERIALIZED VIEW stem_greek_cooccurrence_clean;
REFRESH MATERIALIZED VIEW stem_greek_lemma_cooccurrence;
REFRESH MATERIALIZED VIEW stem_greek_cooccurrence_enriched;
```

---

## Source Data

- **CATSS Parallel Alignment**: UPenn CCAT (46 books of Hebrew Bible)
- **Greek Lemmas**: MorphGNT (NT morphological data, normalized for sigma variants)
- **Hebrew Segmentation**: Rule-based prefix/stem/suffix splitting
- **Strong's Numbers**: ETCBC database (`old_testament.hebrewdata` table, `combined_heb` and `strongs` columns)

---

## Design Principles

1. **Immutable source**: `catss_segmented_groups.jsonl` is the authoritative source
2. **Reversible segmentation**: `prefix + stem + suffix` reconstructs the original surface
3. **No invented data**: Only transformations of supplied corpora
4. **Heuristic classification**: Hebrew POS based on morphological patterns, not external lexicons
5. **Strong's as primary key**: Bridge tables enable interlinear lookup by Strong's number
