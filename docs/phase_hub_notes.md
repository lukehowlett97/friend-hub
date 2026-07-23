# Hub Notes V1

## Implemented Scope

Hub Notes are room-scoped text items with a canonical `notes` table and a mirrored `hub_items` row. The note's stable reference is generated from a room-local sequence, so `#N-1` can safely mean different notes in different rooms.

V1 supports:

- `owner_only` notes: creator or room admin can edit.
- `collaborative` notes: room members can edit title/body; settings remain creator/admin-only.
- `append_only` as a stored mode for compatibility, with structured entries deferred.
- existing generic comments as the V1 discussion/contribution surface.
- note revisions for auditable edits.
- home pinning through `hub_items.pinned_to_home`.
- room-scoped search and `#N-*` reference lookup.
- mobile-first Notes list and detail pages.

## Backend Shape

The main additions are:

- `backend/migrations/047_add_hub_notes.sql`
- `backend/app/models/note.py`
- `backend/app/domains/notes/`
- `backend/app/api/v1/notes_router.py`

The notes API returns backend-derived permissions on every note payload:

```json
{
  "can_edit": true,
  "can_delete": true,
  "can_pin": true,
  "can_comment": true,
  "can_add_entry": false,
  "can_view_revisions": true
}
```

## Frontend Shape

The main additions are:

- `/notes`
- `/notes/:id`
- `frontend/src/pages/NotesPage.jsx`
- `frontend/src/pages/NoteDetailPage.jsx`
- `frontend/src/components/Notes/NoteCard.jsx`
- `frontend/src/components/Notes/NoteEditor.jsx`

Pinned notes, chat reference popups, home activity, search results, and item navigation route notes to `/notes/:id`.

## Deferred

- dedicated `note_entries`
- `suggest_changes`
- rich text editing
- real-time collaborative editing
- structured links between notes and photos/events/polls/reminders/locations
- direct AI mutation of existing notes

## Verification

- `poetry run python -m compileall app`
- `poetry run python -m unittest tests.test_notes`
- `npm run build`

Older router tests could not be run in this environment because the current Poetry environment is missing `PIL`, which is imported by the existing photo service.

