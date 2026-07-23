from pydantic import BaseModel


NOTE_TYPES = {"general", "idea", "memory", "story", "plan", "recommendation", "rule"}
EDIT_MODES = {"owner_only", "collaborative", "append_only"}


class NoteCreateRequest(BaseModel):
    title: str
    body: str = ""
    note_type: str = "general"
    edit_mode: str = "owner_only"
    is_pinned: bool = False
    reference_tag: str | None = None


class NoteUpdateRequest(BaseModel):
    title: str | None = None
    body: str | None = None
    note_type: str | None = None
    edit_mode: str | None = None
    is_pinned: bool | None = None
    reference_tag: str | None = None


class NoteCommentCreateRequest(BaseModel):
    content: str


class NotePermissionsResponse(BaseModel):
    can_edit: bool
    can_delete: bool
    can_pin: bool
    can_comment: bool
    can_add_entry: bool
    can_view_revisions: bool


class NoteResponse(BaseModel):
    id: int
    room_id: str
    group_id: int | None
    room_sequence: int
    title: str
    body: str
    note_type: str
    edit_mode: str
    created_by_user_id: str | None
    creator: dict | None = None
    hub_item: dict | None = None
    short_id: str | None = None
    pinned_to_home: bool = False
    comment_count: int = 0
    revision_count: int = 0
    permissions: NotePermissionsResponse
    archived_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class NotesListResponse(BaseModel):
    notes: list[NoteResponse]
    total: int


class NoteDetailResponse(BaseModel):
    note: NoteResponse


class NoteRevisionResponse(BaseModel):
    id: int
    note_id: int
    changed_by_user_id: str | None
    changer: dict | None = None
    before_title: str | None = None
    after_title: str | None = None
    before_body: str | None = None
    after_body: str | None = None
    before_note_type: str | None = None
    after_note_type: str | None = None
    before_edit_mode: str | None = None
    after_edit_mode: str | None = None
    created_at: str | None = None


class NoteRevisionsResponse(BaseModel):
    revisions: list[NoteRevisionResponse]
    total: int


class NoteCommentResponse(BaseModel):
    id: int
    target_type: str
    target_id: int
    content: str
    creator: dict | None = None
    created_at: str | None = None
    updated_at: str | None = None


class NoteCommentsResponse(BaseModel):
    comments: list[NoteCommentResponse]
    total: int
