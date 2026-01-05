# Real Bible Translation (RBT) Project

A Django web application for Bible translation editing, display, and comprehensive search across Hebrew, Greek, and English texts. Features agentic AI-assisted translation tools and multi-schema PostgreSQL database architecture.

🔗 **Live Site**: [read.realbible.tech](https://read.realbible.tech)

## Overview

The RBT Project is a sophisticated Bible study and translation platform that provides:
- **Multi-language search**: Search across Old Testament Hebrew, New Testament Greek, and English translations
- **Interlinear display**: Word-by-word Hebrew and Greek analysis with Fuerst, Gesenius, and Strong's concordance
- **Translation editing**: Authenticated tools to edit and manage Bible text
- **AI integration**: Google Gemini API for translation assistance with repetitive tasks
- **Live search**: Real-time AJAX search with results from multiple data sources

## Architecture

### Technology Stack
- **Backend**: Django 4.x (Python)
- **Database**: PostgreSQL with multiple schemas
- **Frontend**: Vanilla JavaScript with modern ES6+
- **Deployment**: Railway.app with Gunicorn
- **Static Files**: WhiteNoise middleware

### Database Structure

#### Multi-Schema PostgreSQL Design
The application uses separate PostgreSQL schemas for different text collections:

**Django ORM Tables** (default schema):
- `genesis` - Genesis text with HTML formatting
- `englxxup` - English LXX translation
- `litv` - J.P. Greene's Literal Translation
- `genesis_footnotes` - Genesis footnotes
- `translation_updates` - Translation change tracking

**Raw SQL Schemas** (accessed via `db_utils.py`):
- `old_testament` - OT books (except Genesis)
  - `ot` table: book, chapter, verse, HTML, Hebrew text
  - `hebrewdata` table: Word-level Hebrew analysis with Strong's numbers
  - `ot_consonantal` table: Consonantal Hebrew text (vowels stripped)
- `new_testament` - NT books
  - `nt` table: book, chapter, verse, RBT translation, Greek text
  - Individual book footnote tables
- `rbt_greek` - Greek lexicon
  - `strongs_greek` table: Strong's Greek concordance with morphology
- Additional schemas for apocryphal texts (e.g., `joseph_aseneth`)

#### Database Connection Pattern
```python
# Django ORM (Genesis only)
Genesis.objects.filter(chapter=1, verse=1)

# Raw SQL (Old Testament)
with get_db_connection() as conn:
    cursor.execute("SET search_path TO old_testament")
    cursor.execute("SELECT * FROM ot WHERE book = %s", (book,))

# Raw SQL (New Testament)
with get_db_connection() as conn:
    cursor.execute("SET search_path TO new_testament")
    cursor.execute("SELECT * FROM nt WHERE book = %s", (book,))
```

## Project Structure

```
hebrewtool/
├── hebrewtool/          # Django project settings
│   ├── settings.py      # Main configuration
│   ├── urls.py          # Root URL routing
│   └── wsgi.py          # WSGI application entry
├── search/              # Public reading interface
│   ├── views.py         # Main views (search, verse display)
│   ├── db_utils.py      # Database connection utilities
│   ├── models.py        # Django models (Genesis, etc.)
│   ├── urls.py          # Search app URLs
│   └── templates/       # Public-facing templates
│       ├── search_input.html        # Search page with live AJAX
│       ├── search_results_full.html # Paginated results page
│       ├── verse.html               # Single verse display
│       └── chapter.html             # Chapter view
├── translate/           # Authenticated editing interface
│   ├── views.py         # Editor views, AI translation
│   ├── translator.py    # Translation utilities
│   ├── db_utils.py      # Translation DB utilities
│   └── templates/       # Editor templates
├── static/
│   └── js/
│       └── search.js    # Live search functionality
└── scripts/             # Database maintenance scripts
```

## Core Applications

### `search` App - Public Interface

**Main View**: `search(request)` in `views.py`
- Handles book/chapter/verse display
- Returns `search_input.html` for keyword searches (JavaScript handles the search)
- Caches verse data with Django cache framework

**Search API**: `search_api(request)` at `/api/live/`
- Query params: `q` (query), `scope` (all/ot/nt/hebrew/greek/footnotes), `limit`, `page`
- Returns JSON with results from 6+ database tables
- Script detection for Hebrew/Greek/Latin text

**Key Functions**:
- `get_results(book, chapter, verse)` - Central verse fetching with caching
- `search_results_page(request)` - Full paginated search results

### `translate` App - Editor Interface

**All routes require `@login_required` authentication**

**Main Features**:
- `edit()` - OT chapter editor
- `edit_nt_chapter()` - NT chapter editor  
- `translate()` - AI-assisted translation with Google Gemini
- `find_and_replace_nt()` / `find_and_replace_ot()` - Bulk text operations with undo
- `update_hebrew_data()` - Update Hebrew word data

**AI Translation**:
```python
from google import genai
client = genai.Client(api_key=GEMINI_API_KEY)
response = client.models.generate_content(
    model='gemini-2.0-flash-exp',
    contents=prompt
)
```

## Development Setup

### Prerequisites
- Python 3.12+
- PostgreSQL 17
- Railway CLI (for deployment)

### Environment Variables
Create a `.env` file or set environment variables:

```bash
# Required
GEMINI_API_KEY=xxx              # Google Gemini API key
DATABASE_URL=postgresql://...   # PostgreSQL connection string
SECRET_KEY=xxx                  # Django secret key

# Optional
DEBUG=True                      # Development mode
ALLOWED_HOSTS=localhost,127.0.0.1
```

### Installation

```bash
# Clone repository
git clone <repo-url>
cd webapp_psg

# Install dependencies
pip install -r requirements.txt

# Run migrations (Genesis tables only)
python manage.py migrate

# Create superuser for admin access
python manage.py createsuperuser

# Collect static files
python manage.py collectstatic

# Run development server
python manage.py runserver
```

### Database Setup

The database schemas must be set up separately.


## API Endpoints

### Search API

**`GET /api/live/`**
```
Parameters:
- q (required): Search query
- scope: all|ot|nt|hebrew|greek|footnotes (default: all)
- limit: Results per category (default: 20, max: 100)
- page: Page number (default: 1)

Response:
{
  "query": "love",
  "scope": "all",
  "type": "keyword",
  "script_detected": {"hebrew": false, "greek": false, "latin": true},
  "results": {
    "ot_verses": [...],
    "ot_hebrew": [...],
    "nt_verses": [...],
    "nt_greek": [...],
    "footnotes": [...]
  },
  "counts": {
    "ot_verses": 120,
    "ot_hebrew": 594,
    ...
  },
  "total": 1500
}
```

## Key Features

### Search Functionality
- **Live AJAX Search**: Real-time results as you type
- **Multi-table Search**: Searches 6+ tables simultaneously
  - OT verses (Genesis + old_testament.ot)
  - Hebrew words (old_testament.hebrewdata)
  - Consonantal text (old_testament.ot_consonantal)
  - NT verses (new_testament.nt)
  - Greek words (rbt_greek.strongs_greek)
  - Footnotes (multiple tables)
- **Script Detection**: Automatically detects Hebrew, Greek, or Latin text
- **Virtual Keyboards**: On-screen Hebrew and Greek keyboards
- **Pagination**: Full results page with pagination

### Caching Strategy
```python
# Cache key format: {book}_{chapter}_{verse}_v2
cache_key = f'Genesis_1_1_v2'
cached_data = cache.get(cache_key)

if not cached_data:
    # Fetch from database
    data = fetch_verse_data(book, chapter, verse)
    cache.set(cache_key, data)
```

**Cache invalidation**: Automatically cleared after edits in translator views

### Footnote System
- **Format**: `{chapter}-{verse}-{number}[letter]` (e.g., `1-1-1`, `3-16-2a`)
- **Links**: `<a href="?footnote=1-1-1">` in verse HTML
- **Tables**: `{book}_footnotes` with `footnote_id` and `footnote_html` columns

## Common Tasks

### Adding a New Bible Book

1. **Create schema/table** in PostgreSQL with required columns
2. **Update book lists** in `translator.py`:
   ```python
   old_testament_books = [..., 'new_book']
   book_abbreviations['new_book'] = 'Nbk'
   ```
3. **Create footnote table**: `{book}_footnotes` with `footnote_id`, `footnote_html`
4. **Update `get_results()`** in `search/views.py` to handle new book data
5. **Add to book browser** in `search_input.html`

### Modifying Verse Display

Edit template files in `search/templates/`:
- `verse.html` - Single verse view
- `chapter.html` - Chapter view
- Use `{{ rbt|safe }}` for HTML content
- Load custom tags: `{% load custom_tags %}`

### Managing Static Files

```bash
# Collect static files
python manage.py collectstatic --noinput

# Clear and rebuild
python manage.py collectstatic --noinput --clear
```

Static files are served by WhiteNoise in production.

## Testing

Currently manual testing via:
- Admin interface: `/edit/`, `/edit_nt_chapter/`
- Public interface: `/`, `/search/`
- API testing: `curl http://localhost:8000/api/live/?q=love&limit=5`

## Logging

Logs are written to `RBT_error.log`:
- Daily rotation
- 7-day retention
- Configured in `settings.py`

## Security Notes

- All `/translate/*` and `/edit*` routes require authentication
- Login URL: `/accounts/login/`
- CSRF protection enabled for all forms
- Secure cookie settings in production (HTTPS only)

## Contributing

### Code Style
- Follow PEP 8 for Python code
- Use meaningful variable names
- Add docstrings to functions
- Comment complex logic

### Database Changes
- Never commit migrations to old_testament/new_testament schemas
- Only create migrations for Django ORM models (Genesis, etc.)
- Test schema changes locally before deploying

### Pull Request Process
1. Create feature branch
2. Test changes locally
3. Update this README if needed
4. Submit PR with clear description

## Support

For questions or issues:
- GitHub Issues: [Create an issue]

## Acknowledgments

- ETCBC BHSA database for Hebrew morphology, data graph
- Strong's Concordance for lexicon data
