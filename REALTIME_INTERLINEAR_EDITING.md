# Real-Time Interlinear Word Editing

## Overview
This feature allows you to click on any English word in the Greek interlinear display and edit it in real-time, with updates immediately applied to the database.

## How It Works

### User Experience
1. **Navigate** to any NT verse in the edit interface (`/edit/`)
2. **Click** on any English word in the interlinear (the words under the Greek text)
3. The word becomes **editable** with a yellow highlight
4. **Type** your new translation
5. Press **Enter** to save or **Escape** to cancel
6. A **"✓ Saved"** indicator appears briefly to confirm the update
7. **All instances** of that word on the page update immediately

### What Happens Behind the Scenes
1. **Data Storage**: Each `<span class="eng">` element now contains:
   - `data-strongs`: Strong's number (e.g., "G932")
   - `data-lemma`: Greek lemma
   - `contenteditable="false"` (enabled on click)

2. **Database Update**: When you save:
   - Updates `rbt_greek.strongs_greek` table (matches `interlinear_apply.py` logic)
   - Updates both strongs and lemma keys in `InterlinearConfig.mapping` JSON
   - Saves to `interlinear_english.json` for backward compatibility
   - Clears affected caches

3. **Real-Time Sync**: All matching words on the current page update instantly

## Technical Implementation

### Files Modified
- **`search/views/chapter_views_part1.py`**: Added `data-strongs` and `data-lemma` attributes to interlinear generation (line 772)
- **`translate/views.py`**: Added `update_interlinear_word()` endpoint
- **`translate/urls.py`**: Added route `/api/update-interlinear-word/`
- **`translate/templates/edit_nt_verse.html`**: Added CSS styles and script reference
- **`static/interlinear-editor.js`**: New JavaScript file with editing logic

### API Endpoint
```
POST /api/update-interlinear-word/
Content-Type: application/json

{
  "strongs": "G932",
  "lemma": "βασιλεία", 
  "new_english": "kingdom"
}

Response:
{
  "success": true,
  "old_english": "kingship",
  "new_english": "kingdom",
  "strongs": "G932",
  "lemma": "βασιλεία",
  "message": "Updated 'kingship' → 'kingdom'"
}
```

### CSS Classes
- `.eng`: Base styling with hover effect
- `.eng[contenteditable="true"]`: Editing state (yellow highlight)
- `.eng-save-indicator`: Success/saving feedback
- `.eng-error-indicator`: Error feedback

### JavaScript Functions
- `activateEditing(span)`: Enable contenteditable and select text
- `deactivateEditing(span)`: Restore original text, disable editing
- `saveAndDeactivate(span)`: Save via AJAX, update database
- `updateAllInstances(strongs, lemma, text)`: Sync all words on page
- `showSuccess/showError(span, msg)`: Visual feedback

## Advantages Over Old Workflow

### Old Workflow (Multi-Step)
1. Edit field in `edit_nt_verse.html`
2. Save to `interlinear_english.json`
3. Download JSON file locally
4. Run `python interlinear_apply.py`
5. Wait for batch update to complete
6. Clear caches manually

### New Workflow (One-Click)
1. Click word → edit → press Enter
2. ✅ Done! (Database updated, caches cleared, page synced)

**Result**: From 6 manual steps to 1 click. Updates happen in ~200ms instead of minutes.

## Compatibility Notes
- **Backward Compatible**: Still saves to `interlinear_english.json` for any legacy scripts
- **Database First**: Updates PostgreSQL immediately (no need to run `interlinear_apply.py`)
- **Cache Management**: Automatically clears affected verse caches
- **Multi-User Safe**: Uses Django's transaction system

## Keyboard Shortcuts
- **Enter**: Save changes
- **Escape**: Cancel and restore original text
- **Click outside**: Auto-save changes

## Security
- ✅ Requires `@login_required` authentication
- ✅ Uses Django CSRF protection
- ✅ Validates all input parameters
- ✅ Uses parameterized SQL queries
- ✅ Logs all changes with username

## Testing
To test the feature:
1. Start dev server: `python manage.py runserver`
2. Navigate to: `http://localhost:8000/edit/?book=Mat&chapter=5&verse=1`
3. Click any English word in the interlinear section
4. Edit and press Enter
5. Check that the word updates everywhere on the page
6. Verify in database: `SELECT * FROM rbt_greek.strongs_greek WHERE strongs = 'G####';`

## Future Enhancements
- [ ] Add undo/redo functionality
- [ ] Show all verses affected by a word change
- [ ] Bulk edit mode for multiple words
- [ ] Translation history/audit log viewer
- [ ] Export/import translation sets
