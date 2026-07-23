"""AI API endpoints for Hub Memory and Suggestions."""
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.router import _current_user_or_401, _is_owner_user
from app.domains.ai.repository import AIMemoryRepository, AISuggestionRepository
from app.domains.ai.summary_service import create_summary_service, HubSummaryService
from app.domains.ai.hub_agent_service import SharedHubBotService
from app.domains.ai.agent_run_repository import AgentRunRepository
from app.models.ai_memory import AIMemoryEntry, AISuggestion
from app.models.ai_agent_run import AIAgentRun
from app.models.database import get_db_session
from app.models.hub_item import HubItem, HubItemType
from app.models.planning import DEFAULT_GROUP_SLUG, Group
from app.models.room import DEFAULT_ROOM_ID
from pydantic import BaseModel
from sqlalchemy import select

router = APIRouter(prefix="/api/v1/ai", tags=["ai"])


# ── Request/Response Models ───────────────────────────────────────────────────


class SummarizeChatRequest(BaseModel):
    hours: int = 24
    max_messages: int = 100


class SummarizeChatResponse(BaseModel):
    summary: str
    memories_created: int
    suggestions_created: int
    memory_entries: list
    suggestions: list


class MemoryEntryResponse(BaseModel):
    id: str
    memory_type: str
    title: str | None
    content: str
    source_type: str | None
    source_id: str | None
    confidence: float | None
    tags: list
    created_by: str
    created_at: str
    updated_at: str


class MemoriesResponse(BaseModel):
    memories: list[MemoryEntryResponse]
    total: int


class SuggestionResponse(BaseModel):
    id: str
    suggestion_type: str
    title: str
    body: str | None
    status: str
    proposed_hub_item_type: str | None
    proposed_payload: dict | None
    source_memory_ids: list
    created_hub_item_id: str | None
    created_at: str
    updated_at: str


class SuggestionsResponse(BaseModel):
    suggestions: list[SuggestionResponse]
    total: int


class AcceptSuggestionResponse(BaseModel):
    success: bool
    suggestion: SuggestionResponse
    created_hub_item: dict | None = None
    message: str


class RejectSuggestionResponse(BaseModel):
    success: bool
    suggestion: SuggestionResponse
    message: str


class HubBotChatRequest(BaseModel):
    message: str
    dry_run: bool = False
    include_debug: bool = False


class HubBotChatResponse(BaseModel):
    reply: str
    created_memory_count: int
    created_suggestion_count: int
    suggested_actions: list[str]
    provider: str | None = None
    model: str | None = None
    debug: dict | None = None
    draft_actions: list[dict] = []
    created_items: list[dict] = []


class AgentRunResponse(BaseModel):
    id: str
    status: str
    mode: str
    provider: str
    model: str | None
    user_message: str | None
    prompt_text: str | None
    raw_response: str | None
    parsed_response: dict | None
    validation_errors: list | None
    created_memory_ids: list | None
    created_suggestion_ids: list | None
    tool_calls: list | None
    duration_ms: int | None
    error_message: str | None
    created_at: str
    completed_at: str | None


class AgentRunsResponse(BaseModel):
    runs: list[AgentRunResponse]
    total: int


def _agent_run_payload(run: AIAgentRun) -> dict:
    """Convert AIAgentRun to response payload."""
    return {
        "id": str(run.id),
        "status": run.status,
        "mode": run.mode,
        "provider": run.provider,
        "model": run.model,
        "user_message": run.user_message,
        "prompt_text": run.prompt_text,
        "raw_response": run.raw_response,
        "parsed_response": run.parsed_response,
        "validation_errors": run.validation_errors,
        "created_memory_ids": run.created_memory_ids,
        "created_suggestion_ids": run.created_suggestion_ids,
        "tool_calls": run.tool_calls,
        "duration_ms": run.duration_ms,
        "error_message": run.error_message,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
    }


# ── Helper Functions ──────────────────────────────────────────────────────────


def _memory_payload(entry: AIMemoryEntry) -> dict:
    """Convert AIMemoryEntry to response payload."""
    return {
        "id": str(entry.id),
        "memory_type": entry.memory_type,
        "title": entry.title,
        "content": entry.content,
        "source_type": entry.source_type,
        "source_id": str(entry.source_id) if entry.source_id else None,
        "confidence": entry.confidence,
        "tags": entry.tags or [],
        "created_by": entry.created_by,
        "created_at": entry.created_at.isoformat() if entry.created_at else None,
        "updated_at": entry.updated_at.isoformat() if entry.updated_at else None,
    }


def _suggestion_payload(suggestion: AISuggestion) -> dict:
    """Convert AISuggestion to response payload."""
    return {
        "id": str(suggestion.id),
        "suggestion_type": suggestion.suggestion_type,
        "title": suggestion.title,
        "body": suggestion.body,
        "status": suggestion.status,
        "proposed_hub_item_type": suggestion.proposed_hub_item_type,
        "proposed_payload": suggestion.proposed_payload,
        "source_memory_ids": suggestion.source_memory_ids or [],
        "created_hub_item_id": str(suggestion.created_hub_item_id) if suggestion.created_hub_item_id else None,
        "created_at": suggestion.created_at.isoformat() if suggestion.created_at else None,
        "updated_at": suggestion.updated_at.isoformat() if suggestion.updated_at else None,
    }


def _hub_item_payload(item: HubItem) -> dict:
    """Convert HubItem to response payload."""
    return {
        "id": str(item.id),
        "short_id": item.short_id,
        "type": item.item_type,
        "title": item.title,
        "body": item.body,
        "tags": item.tags or [],
        "status": item.status,
    }


async def _get_default_group(db: AsyncSession) -> Optional[Group]:
    """Get the default group."""
    result = await db.execute(
        select(Group).where(Group.slug == DEFAULT_GROUP_SLUG)
    )
    return result.scalar_one_or_none()


# ── API Endpoints ─────────────────────────────────────────────────────────────


@router.post("/summarise-chat", response_model=SummarizeChatResponse)
async def summarise_chat(
    request: SummarizeChatRequest,
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db_session),
):
    """Generate a chat summary and create AI memories and suggestions.
    
    This endpoint:
    1. Fetches recent chat messages
    2. Analyzes them with an LLM (or fake LLM for testing)
    3. Creates memory entries for important information
    4. Generates suggestions for Hub Items
    
    Requires authentication.
    """
    user = await _current_user_or_401(authorization, db)

    from app.domains.ai.summary_service import create_llm_client
    llm_client = create_llm_client()
    service = create_summary_service(db, llm_client=llm_client)

    result = await service.summarize_chat(
        hours=request.hours,
        max_messages=request.max_messages,
        user_message="ad-hoc summary requested via chat button",
    )

    return SummarizeChatResponse(
        summary=result["summary"],
        memories_created=result["memories_created"],
        suggestions_created=result["suggestions_created"],
        memory_entries=[_memory_payload(m) for m in result["memory_entries"]],
        suggestions=[_suggestion_payload(s) for s in result["suggestions"]],
    )


@router.get("/memories", response_model=MemoriesResponse)
async def get_memories(
    limit: int = 50,
    memory_type: Optional[str] = None,
    source_type: Optional[str] = None,
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db_session),
):
    """List AI memory entries.
    
    Optional filters:
    - memory_type: Filter by type (e.g., daily_summary, weekly_summary)
    - source_type: Filter by source (e.g., chat, hub_item, manual)
    
    Requires authentication.
    """
    user = await _current_user_or_401(authorization, db)
    
    repo = AIMemoryRepository(db)
    memories = await repo.list_recent(
        limit=limit,
        memory_type=memory_type,
        source_type=source_type,
    )
    total = await repo.count()
    
    return MemoriesResponse(
        memories=[_memory_payload(m) for m in memories],
        total=total,
    )


@router.get("/suggestions", response_model=SuggestionsResponse)
async def get_suggestions(
    status: Optional[str] = None,
    suggestion_type: Optional[str] = None,
    limit: int = 50,
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db_session),
):
    """List AI suggestions.
    
    Optional filters:
    - status: Filter by status (pending, accepted, rejected, archived)
    - suggestion_type: Filter by type (e.g., poll, event, reminder)
    
    Requires authentication.
    """
    user = await _current_user_or_401(authorization, db)
    
    repo = AISuggestionRepository(db)
    
    if status == "pending":
        suggestions = await repo.list_pending(limit=limit)
    else:
        suggestions = await repo.list_recent(
            limit=limit,
            status=status,
            suggestion_type=suggestion_type,
        )
    
    total = await repo.count(status=status)
    
    return SuggestionsResponse(
        suggestions=[_suggestion_payload(s) for s in suggestions],
        total=total,
    )


@router.post("/suggestions/{suggestion_id}/accept", response_model=AcceptSuggestionResponse)
async def accept_suggestion(
    suggestion_id: str,
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db_session),
):
    """Accept a suggestion and optionally create a Hub Item.
    
    If the suggestion has a proposed_hub_item_type and proposed_payload,
    a Hub Item will be created. Otherwise, the suggestion is just marked
    as accepted.
    
    Requires authentication.
    """
    user = await _current_user_or_401(authorization, db)
    
    # Parse suggestion ID
    try:
        suggestion_uuid = uuid.UUID(suggestion_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid suggestion ID")
    
    # Get suggestion
    repo = AISuggestionRepository(db)
    suggestion = await repo.get_by_id(suggestion_uuid)
    
    if not suggestion:
        raise HTTPException(status_code=404, detail="Suggestion not found")
    
    if suggestion.status != "pending":
        raise HTTPException(
            status_code=400,
            detail=f"Suggestion is already {suggestion.status}",
        )
    
    created_hub_item = None
    message = "Suggestion accepted."
    
    # Create Hub Item if proposed
    if suggestion.proposed_hub_item_type and suggestion.proposed_payload:
        group = await _get_default_group(db)
        if not group:
            raise HTTPException(status_code=400, detail="No default group found")
        
        payload = suggestion.proposed_payload
        hub_item_type = suggestion.proposed_hub_item_type
        
        # Validate hub item type
        valid_types = [t.value for t in HubItemType]
        if hub_item_type not in valid_types:
            # Mark as accepted but don't create item
            await repo.update_status(suggestion_uuid, "accepted")
            message = f"Suggestion accepted but could not create Hub Item: invalid type '{hub_item_type}'."
            return AcceptSuggestionResponse(
                success=True,
                suggestion=_suggestion_payload(suggestion),
                message=message,
            )
        
        # Calculate next sequence for short_id
        from sqlalchemy import func
        result = await db.execute(
            select(func.max(HubItem.type_sequence)).where(HubItem.item_type == hub_item_type)
        )
        next_seq = (result.scalar() or 0) + 1
        
        # Create Hub Item
        prefixes = {"idea": "I", "poll": "P", "reminder": "R", "event": "E", "note": "N"}
        prefix = prefixes.get(hub_item_type, "N")
        
        hub_item = HubItem(
            group_id=group.id,
            room_id=DEFAULT_ROOM_ID,
            item_type=hub_item_type,
            type_sequence=next_seq,
            short_id=f"#{prefix}-{next_seq}",
            title=payload.get("title", "Untitled")[:220],
            body=payload.get("body"),
            tags=payload.get("tags", []),
            created_by_user_id=user.id,
        )
        db.add(hub_item)
        await db.flush()
        await db.refresh(hub_item)
        
        # Link suggestion to created Hub Item
        await repo.update_status(
            suggestion_uuid,
            "accepted",
            created_hub_item_id=hub_item.id,
        )
        
        created_hub_item = _hub_item_payload(hub_item)
        message = f"Suggestion accepted and {hub_item.short_id} created."
    else:
        # Just mark as accepted (no Hub Item to create)
        await repo.update_status(suggestion_uuid, "accepted")
        message = "Suggestion accepted (no Hub Item to create)."
    
    # Refresh suggestion to get updated status
    await db.refresh(suggestion)
    
    return AcceptSuggestionResponse(
        success=True,
        suggestion=_suggestion_payload(suggestion),
        created_hub_item=created_hub_item,
        message=message,
    )


@router.post("/suggestions/{suggestion_id}/reject", response_model=RejectSuggestionResponse)
async def reject_suggestion(
    suggestion_id: str,
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db_session),
):
    """Reject a suggestion.
    
    The suggestion will be marked as rejected and archived.
    
    Requires authentication.
    """
    user = await _current_user_or_401(authorization, db)
    
    # Parse suggestion ID
    try:
        suggestion_uuid = uuid.UUID(suggestion_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid suggestion ID")
    
    # Get suggestion
    repo = AISuggestionRepository(db)
    suggestion = await repo.get_by_id(suggestion_uuid)
    
    if not suggestion:
        raise HTTPException(status_code=404, detail="Suggestion not found")
    
    if suggestion.status != "pending":
        raise HTTPException(
            status_code=400,
            detail=f"Suggestion is already {suggestion.status}",
        )
    
    # Mark as rejected
    await repo.update_status(suggestion_uuid, "rejected")
    await db.refresh(suggestion)
    
    return RejectSuggestionResponse(
        success=True,
        suggestion=_suggestion_payload(suggestion),
        message="Suggestion rejected.",
    )


@router.get("/agent-runs", response_model=AgentRunsResponse)
async def list_agent_runs(
    limit: int = 50,
    status: Optional[str] = None,
    mode: Optional[str] = None,
    provider: Optional[str] = None,
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db_session),
):
    """List recent AI agent runs for inspection and debugging.
    
    Optional filters:
    - status: Filter by status (running, completed, failed)
    - mode: Filter by mode (chat_summary, etc.)
    - provider: Filter by provider (fake, ollama, openrouter)
    
    Requires authentication.
    """
    user = await _current_user_or_401(authorization, db)
    
    repo = AgentRunRepository(db)
    runs = await repo.list_recent(
        limit=limit,
        status=status,
        mode=mode,
        provider=provider,
    )
    total = await repo.count(status=status, mode=mode)
    
    return AgentRunsResponse(
        runs=[_agent_run_payload(r) for r in runs],
        total=total,
    )


@router.get("/agent-runs/{run_id}", response_model=AgentRunResponse)
async def get_agent_run(
    run_id: str,
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db_session),
):
    """Get a single agent run with full details for debugging.
    
    Returns complete prompt, response, and execution metadata.
    
    Requires authentication.
    """
    user = await _current_user_or_401(authorization, db)
    
    try:
        run_uuid = uuid.UUID(run_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid run ID")
    
    repo = AgentRunRepository(db)
    run = await repo.get_by_id(run_uuid)
    
    if not run:
        raise HTTPException(status_code=404, detail="Agent run not found")
    
    return AgentRunResponse(**_agent_run_payload(run))


@router.post("/hub-bot-chat", response_model=HubBotChatResponse)
async def hub_bot_chat(
    request: HubBotChatRequest,
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db_session),
):
    """Chat with Hub Bot in the Lab interface.
    
    Uses the shared HubAgentService (same as live Hub Bot) for consistent
    prompt building, context handling, and LLM provider usage.
    
    Supports keyword commands for Lab convenience:
    - "summarise" → Generate chat summary
    - "unresolved" → Show unresolved plans
    - "polls" / "suggest poll" → Create poll suggestion
    - "memories" → Show recent memories
    - Otherwise → LLM-powered response with full context
    
    Always returns valid JSON. Never returns HTML or plain text errors.
    
    Requires authentication.
    """
    import logging
    logger = logging.getLogger(__name__)
    
    try:
        user = await _current_user_or_401(authorization, db)
        group = await _get_default_group(db)

        from app.domains.ai.hub_agent_service import SharedHubBotService
        from app.domains.ai.summary_service import create_llm_client

        llm_client = create_llm_client()
        service = SharedHubBotService(db=db, llm_client=llm_client)

        result = await service.process_query(
            query=request.message,
            user_nickname=user.nickname if hasattr(user, "nickname") else "User",
            dry_run=request.dry_run,
            include_debug=request.include_debug,
            group_id=group.id if group else None,
            user_id=user.id,
            source="hub_lab",
        )

        reply = result.reply
        provider_name = getattr(llm_client, "provider_name", "unknown")
        model_name = getattr(llm_client, "model", None)

        if request.include_debug:
            reply += (
                f"\n\n[Debug] Provider: {provider_name}"
                f" | Model: {model_name or 'default'}"
                f" | Runtime: HubAgentRuntime"
            )

        await db.commit()

        return HubBotChatResponse(
            reply=reply,
            created_memory_count=result.created_memory_count,
            created_suggestion_count=result.created_suggestion_count,
            suggested_actions=result.suggested_actions,
            provider=provider_name,
            model=model_name,
            debug=result.debug if request.include_debug else None,
            draft_actions=result.draft_actions,
            created_items=result.created_items,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("hub-bot-chat error: %s", e)
        return HubBotChatResponse(
            reply=f"⚠️ Error: {str(e)}",
            created_memory_count=0,
            created_suggestion_count=0,
            suggested_actions=[],
        )


# ── Usage log ─────────────────────────────────────────────────────────────────


class UsageEventResponse(BaseModel):
    id: int
    provider: str
    model: str | None
    feature: str | None
    command: str | None
    tokens_in: int
    tokens_out: int
    cost_cents: int
    user_id: str | None
    group_id: int | None
    created_at: str


class UsageResponse(BaseModel):
    events: list[UsageEventResponse]
    total_tokens_in: int
    total_tokens_out: int
    total_cost_cents: int


@router.get("/usage", response_model=UsageResponse)
async def get_usage(
    limit: int = Query(default=50, le=200),
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db_session),
):
    """Recent AI usage events. Owner only."""
    user = await _current_user_or_401(authorization, db)
    if not _is_owner_user(user):
        raise HTTPException(status_code=403, detail="Owner only")

    rows = (await db.execute(text(
        "SELECT id, provider, model, feature, command, tokens_in, tokens_out, cost_cents, "
        "user_id, group_id, created_at "
        "FROM ai_usage_log ORDER BY created_at DESC LIMIT :limit"
    ), {"limit": limit})).fetchall()

    totals = (await db.execute(text(
        "SELECT COALESCE(SUM(tokens_in),0), COALESCE(SUM(tokens_out),0), COALESCE(SUM(cost_cents),0) "
        "FROM ai_usage_log WHERE created_at >= date_trunc('month', NOW())"
    ))).first()

    events = [
        UsageEventResponse(
            id=r.id,
            provider=r.provider,
            model=r.model,
            feature=r.feature,
            command=r.command,
            tokens_in=r.tokens_in,
            tokens_out=r.tokens_out,
            cost_cents=r.cost_cents,
            user_id=str(r.user_id) if r.user_id else None,
            group_id=r.group_id,
            created_at=r.created_at.isoformat() if r.created_at else None,
        )
        for r in rows
    ]

    return UsageResponse(
        events=events,
        total_tokens_in=int(totals[0]),
        total_tokens_out=int(totals[1]),
        total_cost_cents=int(totals[2]),
    )
