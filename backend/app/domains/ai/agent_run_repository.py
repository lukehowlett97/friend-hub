"""Repository for AI Agent Runs - tracks LLM interactions for observability."""
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_agent_run import AIAgentRun


class AgentRunRepository:
    """Repository for AI Agent Runs.
    
    Provides CRUD operations and querying for agent run tracking.
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(
        self,
        mode: str,
        provider: str,
        user_message: Optional[str] = None,
        prompt_text: Optional[str] = None,
        model: Optional[str] = None,
    ) -> AIAgentRun:
        """Create a new agent run in 'running' status."""
        run = AIAgentRun(
            mode=mode,
            provider=provider,
            model=model,
            status="running",
            user_message=user_message,
            prompt_text=prompt_text,
        )
        self.db.add(run)
        await self.db.flush()
        await self.db.refresh(run)
        return run

    async def get_by_id(self, run_id: uuid.UUID) -> Optional[AIAgentRun]:
        """Get a run by ID."""
        return await self.db.get(AIAgentRun, run_id)

    async def update(
        self,
        run_id: uuid.UUID,
        status: Optional[str] = None,
        raw_response: Optional[str] = None,
        parsed_response: Optional[dict] = None,
        prompt_text: Optional[str] = None,
        validation_errors: Optional[list] = None,
        created_memory_ids: Optional[List[str]] = None,
        created_suggestion_ids: Optional[List[str]] = None,
        tool_calls: Optional[list] = None,
        duration_ms: Optional[int] = None,
        error_message: Optional[str] = None,
    ) -> Optional[AIAgentRun]:
        """Update a run's fields. Set completed_at on completion/failure."""
        run = await self.db.get(AIAgentRun, run_id)
        if not run:
            return None

        if status is not None:
            run.status = status
        if raw_response is not None:
            run.raw_response = raw_response
        if parsed_response is not None:
            run.parsed_response = parsed_response
        if prompt_text is not None:
            run.prompt_text = prompt_text
        if validation_errors is not None:
            run.validation_errors = validation_errors
        if created_memory_ids is not None:
            run.created_memory_ids = created_memory_ids
        if created_suggestion_ids is not None:
            run.created_suggestion_ids = created_suggestion_ids
        if tool_calls is not None:
            run.tool_calls = tool_calls
        if duration_ms is not None:
            run.duration_ms = duration_ms
        if error_message is not None:
            run.error_message = error_message

        if status in ("completed", "failed"):
            # Use naive UTC datetime to match the model's Column(DateTime) default
            run.completed_at = datetime.utcnow()

        await self.db.flush()
        await self.db.refresh(run)
        return run

    async def mark_completed(
        self,
        run_id: uuid.UUID,
        raw_response: Optional[str] = None,
        parsed_response: Optional[dict] = None,
        validation_errors: Optional[list] = None,
        created_memory_ids: Optional[List[str]] = None,
        created_suggestion_ids: Optional[List[str]] = None,
        duration_ms: Optional[int] = None,
    ) -> Optional[AIAgentRun]:
        """Mark a run as completed with results."""
        return await self.update(
            run_id=run_id,
            status="completed",
            raw_response=raw_response,
            parsed_response=parsed_response,
            validation_errors=validation_errors,
            created_memory_ids=created_memory_ids,
            created_suggestion_ids=created_suggestion_ids,
            duration_ms=duration_ms,
        )

    async def mark_failed(
        self,
        run_id: uuid.UUID,
        error_message: str,
        duration_ms: Optional[int] = None,
    ) -> Optional[AIAgentRun]:
        """Mark a run as failed."""
        return await self.update(
            run_id=run_id,
            status="failed",
            error_message=error_message,
            duration_ms=duration_ms,
        )

    async def list_recent(
        self,
        limit: int = 50,
        mode: Optional[str] = None,
        status: Optional[str] = None,
        provider: Optional[str] = None,
    ) -> List[AIAgentRun]:
        """List recent runs with optional filters."""
        stmt = select(AIAgentRun).order_by(desc(AIAgentRun.created_at))

        if mode:
            stmt = stmt.where(AIAgentRun.mode == mode)
        if status:
            stmt = stmt.where(AIAgentRun.status == status)
        if provider:
            stmt = stmt.where(AIAgentRun.provider == provider)

        stmt = stmt.limit(limit)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def list_failures(
        self,
        limit: int = 20,
        hours: int = 24,
    ) -> List[AIAgentRun]:
        """List recent failed runs."""
        from datetime import timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        
        stmt = (
            select(AIAgentRun)
            .where(AIAgentRun.status == "failed")
            .where(AIAgentRun.created_at >= cutoff)
            .order_by(desc(AIAgentRun.created_at))
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def count(
        self,
        status: Optional[str] = None,
        mode: Optional[str] = None,
    ) -> int:
        """Count runs, optionally filtered."""
        from sqlalchemy import func
        
        stmt = select(func.count(AIAgentRun.id))
        if status:
            stmt = stmt.where(AIAgentRun.status == status)
        if mode:
            stmt = stmt.where(AIAgentRun.mode == mode)
        
        result = await self.db.execute(stmt)
        return result.scalar() or 0