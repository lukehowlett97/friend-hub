import os
import unittest

os.environ["DEBUG"] = "false"
os.environ.setdefault("DATABASE_PASSWORD", "changeme")

from app.domains.notes.schemas import EDIT_MODES, NOTE_TYPES
from app.models.note import Note, NoteRevision


class TestNoteModel(unittest.TestCase):
    def test_required_columns_present(self):
        cols = {column.key for column in Note.__table__.columns}
        for name in {
            "id",
            "room_id",
            "group_id",
            "room_sequence",
            "title",
            "body",
            "note_type",
            "edit_mode",
            "created_by_user_id",
            "archived_at",
            "archived_by",
            "created_at",
            "updated_at",
        }:
            self.assertIn(name, cols)

    def test_revision_columns_present(self):
        cols = {column.key for column in NoteRevision.__table__.columns}
        for name in {
            "note_id",
            "changed_by_user_id",
            "before_title",
            "after_title",
            "before_body",
            "after_body",
            "before_note_type",
            "after_note_type",
            "before_edit_mode",
            "after_edit_mode",
        }:
            self.assertIn(name, cols)

    def test_v1_enums(self):
        self.assertIn("general", NOTE_TYPES)
        self.assertIn("memory", NOTE_TYPES)
        self.assertIn("owner_only", EDIT_MODES)
        self.assertIn("collaborative", EDIT_MODES)
        self.assertIn("append_only", EDIT_MODES)

