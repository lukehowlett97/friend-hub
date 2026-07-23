"""Hub Summary Service - generates chat summaries and suggestions from memory.

This service reuses the existing AI gateway (OpenRouterProvider) from app.ai.gateway
for production use, and provides a FakeLLMClient for testing.
"""
import json
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.gateway import get_provider
from app.config import get_settings
from app.domains.ai.repository import AIMemoryRepository, AISuggestionRepository
from app.domains.ai.agent_run_repository import AgentRunRepository
from app.models.ai_memory import AIMemoryEntry, AISuggestion

logger = logging.getLogger(__name__)

settings = get_settings()


# ── LLM Client Interface ──────────────────────────────────────────────────────


@runtime_checkable
class LLMClient(Protocol):
    """Interface for LLM clients used by the summary service.
    
    This is a higher-level interface than ChatModelProvider - it handles
    the full prompt building and JSON parsing internally.
    """

    async def generate_summary(
        self,
        messages_text: str,
        hub_items_text: str,
        existing_memories_text: str = "",
    ) -> dict:
        """Generate a structured summary from chat and hub items.
        
        Returns a dict with:
        - summary: str - brief summary of conversations
        - memories: list[dict] - memory entries to store
        - suggestions: list[dict] - suggestions to create
        
        Each memory dict has:
        - type: str
        - title: str (optional)
        - content: str
        - tags: list[str] (optional)
        - confidence: float (optional)
        
        Each suggestion dict has:
        - type: str
        - title: str
        - body: str (optional)
        - hub_item_type: str (optional)
        - payload: dict (optional)
        """
        ...


# ── Fake LLM Client for Testing ───────────────────────────────────────────────


class FakeLLMClient:
    """Deterministic fake LLM client for testing.

    Returns sensible test output without calling real APIs.
    """

    provider_name: str = "fake"
    model: str = "fake"

    async def generate_summary(
        self,
        messages_text: str,
        hub_items_text: str,
        existing_memories_text: str = "",
    ) -> dict:
        """Generate deterministic test output."""
        # Analyze the input to create context-aware responses
        has_event = "event" in messages_text.lower() or "party" in messages_text.lower()
        has_food = "food" in messages_text.lower() or "eat" in messages_text.lower() or "lunch" in messages_text.lower()
        has_deadline = "deadline" in messages_text.lower() or "due" in messages_text.lower()
        
        memories = []
        suggestions = []
        
        # Always create a summary memory
        memories.append({
            "type": "daily_summary",
            "title": "Daily Chat Summary",
            "content": f"Chat summary generated at {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}. "
                      f"Discussed various topics including events and plans.",
            "tags": ["summary", "daily"],
            "confidence": 0.9,
        })
        
        # Create context-specific memories
        if has_event:
            memories.append({
                "type": "unresolved_plan",
                "title": "Event Planning Discussion",
                "content": "Group members discussed organizing an event. Details to be finalized.",
                "tags": ["event", "planning"],
                "confidence": 0.7,
            })
            suggestions.append({
                "type": "event",
                "title": "Create Event Poll",
                "body": "Based on the chat discussion, consider creating a poll to decide on event details.",
                "hub_item_type": "poll",
                "payload": {
                    "title": "Event Planning Poll",
                    "body": "Let's decide on the event details together!",
                    "type": "poll",
                },
            })
        
        if has_food:
            memories.append({
                "type": "user_preference",
                "title": "Food Discussion",
                "content": "Group members discussed food preferences and dining options.",
                "tags": ["food", "preferences"],
                "confidence": 0.6,
            })
        
        if has_deadline:
            suggestions.append({
                "type": "reminder",
                "title": "Deadline Reminder",
                "body": "There seems to be an upcoming deadline mentioned. Consider setting a reminder.",
                "hub_item_type": "reminder",
                "payload": {
                    "title": "Upcoming Deadline",
                    "body": "Don't forget about the upcoming deadline!",
                    "type": "reminder",
                },
            })
        
        # Always add a fallback suggestion if none generated
        if not suggestions:
            suggestions.append({
                "type": "summary",
                "title": "Weekly Check-in",
                "body": "Consider doing a weekly check-in to keep everyone aligned.",
                "hub_item_type": None,
                "payload": None,
            })
        
        return {
            "summary": "Generated chat summary with memories and suggestions.",
            "memories": memories,
            "suggestions": suggestions,
        }


# ── Ollama LLM Client ─────────────────────────────────────────────────────────


class OllamaLLMClient:
    """Ollama-based LLM client for local AI inference.
    
    Connects to a local Ollama server for private, offline AI processing.
    """

    provider_name: str = "ollama"

    def __init__(
        self,
        base_url: str = None,
        model: str = None,
        timeout: int = None,
    ):
        self.base_url = (base_url or settings.ollama_base_url).rstrip("/")
        self.model = model or settings.ollama_model
        self.timeout = timeout or settings.ollama_timeout

    async def _check_availability(self) -> bool:
        """Check if Ollama server is available."""
        import httpx
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{self.base_url}/api/tags")
                return resp.status_code == 200
        except Exception:
            return False

    async def generate_summary(
        self,
        messages_text: str,
        hub_items_text: str,
        existing_memories_text: str = "",
    ) -> dict:
        """Generate a structured summary using Ollama."""
        # Check availability first
        if not await self._check_availability():
            raise ConnectionError(
                f"Ollama server not available at {self.base_url}. "
                "Please ensure Ollama is running: ollama serve"
            )

        # Build the prompt with JSON schema requirement
        prompt = self._build_prompt(messages_text, hub_items_text, existing_memories_text)
        
        system_prompt = """You are Hub Bot, an AI assistant for Friend Hub. 
Analyze the chat messages and generate structured memories and suggestions.

Output ONLY valid JSON in this exact format:
{
    "summary": "Brief summary of the conversation",
    "memories": [
        {
            "type": "daily_summary|weekly_summary|decision|unresolved_plan|funny_moment|user_preference|suggestion_context",
            "title": "Short title",
            "content": "Detailed content",
            "tags": ["tag1", "tag2"],
            "confidence": 0.8
        }
    ],
    "suggestions": [
        {
            "type": "poll|event|reminder|idea|tag|summary",
            "title": "Suggestion title",
            "body": "Suggestion description",
            "hub_item_type": "poll|event|reminder|idea|note|null",
            "payload": {"title": "...", "body": "...", "type": "..."} or null
        }
    ]
}

Memory types:
- daily_summary: Brief summary of daily conversations
- weekly_summary: Summary of weekly activity
- decision: Important decisions made
- unresolved_plan: Plans that need follow-up
- funny_moment: Humorous moments worth remembering
- user_preference: User preferences discovered
- suggestion_context: Context for generating suggestions

Rules:
- Create 1-3 memories maximum
- Create 0-2 suggestions maximum
- Only create suggestions that are actionable
- Set confidence between 0.0 and 1.0
- Keep titles under 50 characters
- Keep content under 500 characters"""

        import httpx
        payload = {
            "model": self.model,
            "prompt": prompt,
            "system": system_prompt,
            "stream": False,
            "format": "json",
        }

        async with httpx.AsyncClient(timeout=float(self.timeout)) as client:
            try:
                resp = await client.post(
                    f"{self.base_url}/api/generate",
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()
                
                response_text = data.get("response", "")
                return self._parse_response(response_text)
            except httpx.ConnectError:
                raise ConnectionError(
                    f"Could not connect to Ollama at {self.base_url}. "
                    "Is Ollama running? Try: ollama serve"
                )
            except httpx.TimeoutException:
                raise TimeoutError(
                    f"Ollama request timed out after {self.timeout}s. "
                    "Try a smaller model or increase timeout."
                )

    def _build_prompt(
        self,
        messages_text: str,
        hub_items_text: str,
        existing_memories_text: str,
    ) -> str:
        """Build the prompt for Ollama."""
        parts = ["Analyze the following chat messages and generate memories and suggestions:\n"]
        
        if messages_text:
            parts.append(f"RECENT MESSAGES:\n{messages_text}\n")
        
        if hub_items_text and hub_items_text != "(no hub items)":
            parts.append(f"ACTIVE HUB ITEMS:\n{hub_items_text}\n")
        
        if existing_memories_text:
            parts.append(f"EXISTING MEMORIES:\n{existing_memories_text}\n")
        
        parts.append("\nGenerate JSON output as instructed in the system prompt.")
        return "\n".join(parts)

    def _parse_response(self, response_text: str) -> dict:
        """Parse and validate the JSON response from Ollama."""
        # Try to extract JSON from the response
        json_match = re.search(r'\{[\s\S]*\}', response_text)
        if not json_match:
            logger.warning("No JSON found in Ollama response: %s", response_text[:200])
            return self._get_fallback_response()
        
        try:
            data = json.loads(json_match.group())
            return self._validate_response(data)
        except json.JSONDecodeError as e:
            logger.warning("Invalid JSON in Ollama response: %s", e)
            return self._get_fallback_response()

    def _validate_response(self, data: dict) -> dict:
        """Validate and sanitize the LLM response."""
        result = {
            "summary": str(data.get("summary", "Summary generated."))[:500],
            "memories": [],
            "suggestions": [],
        }
        
        # Validate memories
        valid_memory_types = {
            "daily_summary", "weekly_summary", "decision",
            "unresolved_plan", "funny_moment", "user_preference",
            "suggestion_context"
        }
        
        for mem in data.get("memories", [])[:3]:  # Limit to 3
            if not isinstance(mem, dict):
                continue
            mem_type = mem.get("type", "daily_summary")
            if mem_type not in valid_memory_types:
                mem_type = "daily_summary"
            
            result["memories"].append({
                "type": mem_type,
                "title": str(mem.get("title", ""))[:100],
                "content": str(mem.get("content", ""))[:500],
                "tags": mem.get("tags", [])[:5] if isinstance(mem.get("tags"), list) else [],
                "confidence": min(1.0, max(0.0, float(mem.get("confidence", 0.7)))),
            })
        
        # Validate suggestions
        valid_suggestion_types = {"poll", "event", "reminder", "idea", "tag", "summary"}
        valid_hub_item_types = {"poll", "event", "reminder", "idea", "note", None}
        
        for sug in data.get("suggestions", [])[:2]:  # Limit to 2
            if not isinstance(sug, dict):
                continue
            sug_type = sug.get("type", "summary")
            if sug_type not in valid_suggestion_types:
                sug_type = "summary"
            
            hub_item_type = sug.get("hub_item_type")
            if hub_item_type not in valid_hub_item_types:
                hub_item_type = None
            
            result["suggestions"].append({
                "type": sug_type,
                "title": str(sug.get("title", "Untitled"))[:100],
                "body": str(sug.get("body", ""))[:500],
                "hub_item_type": hub_item_type,
                "payload": sug.get("payload"),
            })
        
        return result

    def _get_fallback_response(self) -> dict:
        """Return a fallback response when parsing fails."""
        return {
            "summary": "Summary generated from chat messages.",
            "memories": [{
                "type": "daily_summary",
                "title": "Chat Summary",
                "content": "A summary was generated from recent messages.",
                "tags": ["summary"],
                "confidence": 0.5,
            }],
            "suggestions": [],
        }


# ── OpenRouter LLM Client (reuses existing gateway) ──────────────────────────


class OpenRouterLLMClient:
    """OpenRouter-based LLM client that reuses the existing gateway.
    
    This client wraps the existing OpenRouterProvider from app.ai.gateway
    to provide the higher-level LLMClient interface needed by HubSummaryService.
    """

    provider_name: str = "openrouter"

    def __init__(self, api_key: str = None, model: str = None):
        self.api_key = api_key or settings.ai_api_key
        self.model = model or settings.ai_default_chat_model
        self._provider = None

    def _get_provider(self):
        """Lazy-load the provider to avoid issues during import."""
        if self._provider is None:
            self._provider = get_provider(self.api_key, settings.ai_api_provider)
        return self._provider

    async def generate_summary(
        self,
        messages_text: str,
        hub_items_text: str,
        existing_memories_text: str = "",
    ) -> dict:
        """Generate a structured summary using OpenRouter."""
        if not self.api_key:
            raise ValueError("OpenRouter API key is not configured")

        # Build the prompt
        prompt = self._build_prompt(messages_text, hub_items_text, existing_memories_text)
        
        system_prompt = """You are Hub Bot, an AI assistant for Friend Hub. 
Analyze the chat messages and generate structured memories and suggestions.

Output ONLY valid JSON in this exact format:
{
    "summary": "Brief summary of the conversation",
    "memories": [
        {
            "type": "daily_summary|weekly_summary|decision|unresolved_plan|funny_moment|user_preference|suggestion_context",
            "title": "Short title",
            "content": "Detailed content",
            "tags": ["tag1", "tag2"],
            "confidence": 0.8
        }
    ],
    "suggestions": [
        {
            "type": "poll|event|reminder|idea|tag|summary",
            "title": "Suggestion title",
            "body": "Suggestion description",
            "hub_item_type": "poll|event|reminder|idea|note|null",
            "payload": {"title": "...", "body": "...", "type": "..."} or null
        }
    ]
}

Memory types:
- daily_summary: Brief summary of daily conversations
- weekly_summary: Summary of weekly activity
- decision: Important decisions made
- unresolved_plan: Plans that need follow-up
- funny_moment: Humorous moments worth remembering
- user_preference: User preferences discovered
- suggestion_context: Context for generating suggestions

Rules:
- Create 1-3 memories maximum
- Create 0-2 suggestions maximum
- Only create suggestions that are actionable
- Set confidence between 0.0 and 1.0
- Keep titles under 50 characters
- Keep content under 500 characters"""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ]

        try:
            provider = self._get_provider()
            response_text, _, _ = await provider.complete_chat(messages, self.model)
            return self._parse_response(response_text)
        except Exception as e:
            logger.error("OpenRouter error: %s", e)
            raise

    def _build_prompt(
        self,
        messages_text: str,
        hub_items_text: str,
        existing_memories_text: str,
    ) -> str:
        """Build the prompt for OpenRouter."""
        parts = ["Analyze the following chat messages and generate memories and suggestions:\n"]
        
        if messages_text:
            parts.append(f"RECENT MESSAGES:\n{messages_text}\n")
        
        if hub_items_text and hub_items_text != "(no hub items)":
            parts.append(f"ACTIVE HUB ITEMS:\n{hub_items_text}\n")
        
        if existing_memories_text:
            parts.append(f"EXISTING MEMORIES:\n{existing_memories_text}\n")
        
        parts.append("\nGenerate JSON output as instructed in the system prompt.")
        return "\n".join(parts)

    def _parse_response(self, response_text: str) -> dict:
        """Parse and validate the JSON response from OpenRouter."""
        # Try to extract JSON from the response
        json_match = re.search(r'\{[\s\S]*\}', response_text)
        if not json_match:
            logger.warning("No JSON found in OpenRouter response: %s", response_text[:200])
            return self._get_fallback_response()
        
        try:
            data = json.loads(json_match.group())
            return self._validate_response(data)
        except json.JSONDecodeError as e:
            logger.warning("Invalid JSON in OpenRouter response: %s", e)
            return self._get_fallback_response()

    def _validate_response(self, data: dict) -> dict:
        """Validate and sanitize the LLM response."""
        result = {
            "summary": str(data.get("summary", "Summary generated."))[:500],
            "memories": [],
            "suggestions": [],
        }
        
        # Validate memories
        valid_memory_types = {
            "daily_summary", "weekly_summary", "decision",
            "unresolved_plan", "funny_moment", "user_preference",
            "suggestion_context"
        }
        
        for mem in data.get("memories", [])[:3]:  # Limit to 3
            if not isinstance(mem, dict):
                continue
            mem_type = mem.get("type", "daily_summary")
            if mem_type not in valid_memory_types:
                mem_type = "daily_summary"
            
            result["memories"].append({
                "type": mem_type,
                "title": str(mem.get("title", ""))[:100],
                "content": str(mem.get("content", ""))[:500],
                "tags": mem.get("tags", [])[:5] if isinstance(mem.get("tags"), list) else [],
                "confidence": min(1.0, max(0.0, float(mem.get("confidence", 0.7)))),
            })
        
        # Validate suggestions
        valid_suggestion_types = {"poll", "event", "reminder", "idea", "tag", "summary"}
        valid_hub_item_types = {"poll", "event", "reminder", "idea", "note", None}
        
        for sug in data.get("suggestions", [])[:2]:  # Limit to 2
            if not isinstance(sug, dict):
                continue
            sug_type = sug.get("type", "summary")
            if sug_type not in valid_suggestion_types:
                sug_type = "summary"
            
            hub_item_type = sug.get("hub_item_type")
            if hub_item_type not in valid_hub_item_types:
                hub_item_type = None
            
            result["suggestions"].append({
                "type": sug_type,
                "title": str(sug.get("title", "Untitled"))[:100],
                "body": str(sug.get("body", ""))[:500],
                "hub_item_type": hub_item_type,
                "payload": sug.get("payload"),
            })
        
        return result

    def _get_fallback_response(self) -> dict:
        """Return a fallback response when parsing fails."""
        return {
            "summary": "Summary generated from chat messages.",
            "memories": [{
                "type": "daily_summary",
                "title": "Chat Summary",
                "content": "A summary was generated from recent messages.",
                "tags": ["summary"],
                "confidence": 0.5,
            }],
            "suggestions": [],
        }


# ── Hub Summary Service ───────────────────────────────────────────────────────


class HubSummaryService:
    """Service for generating chat summaries and AI suggestions.
    
    This service:
    1. Fetches recent chat messages and hub items
    2. Builds a deterministic text bundle
    3. Calls an LLM client (pluggable)
    4. Parses structured JSON output
    5. Stores memory entries and suggestions
    6. Logs every run to ai_agent_runs for observability
    """

    def __init__(
        self,
        db: AsyncSession,
        llm_client: Optional[LLMClient] = None,
    ):
        self.db = db
        self.llm_client = llm_client or FakeLLMClient()
        self.memory_repo = AIMemoryRepository(db)
        self.suggestion_repo = AISuggestionRepository(db)
        self.run_repo = AgentRunRepository(db)

    async def summarize_chat(
        self,
        hours: int = 24,
        max_messages: int = 100,
        dry_run: bool = False,
        user_message: Optional[str] = None,
        room_id: Optional[uuid.UUID] = None,
        start_at: Optional[datetime] = None,
        end_at: Optional[datetime] = None,
        created_by: str = "hub_bot",
    ) -> dict:
        """Summarize recent chat and generate memories/suggestions.

        Args:
            hours: Number of hours of chat history to include
            max_messages: Maximum number of messages to fetch
            dry_run: If True, don't create memories/suggestions but still log the run
            user_message: Optional user message that triggered this run
            room_id: Restrict to one room and stamp created memories with it
            start_at: Explicit window start (naive UTC); overrides hours
            end_at: Explicit window end (naive UTC)
            created_by: Attribution recorded on created memory entries

        Returns:
            dict with:
            - summary: str
            - memories_created: int
            - suggestions_created: int
            - memory_entries: list[AIMemoryEntry]
            - suggestions: list[AISuggestion]
            - agent_run_id: UUID of the logged run (if any)
        """
        import time
        from app.config import get_settings
        
        start_time = time.monotonic()
        settings = get_settings()
        
        # Create agent run record
        run = None
        try:
            run = await self.run_repo.create(
                mode="chat_summary",
                provider=settings.ai_lab_provider,
                model=settings.ai_default_chat_model if settings.ai_lab_provider == "openrouter" else settings.ollama_model,
                user_message=user_message,
            )
        except Exception as e:
            logger.warning("Failed to create agent run record: %s", e)
        
        try:
            # Import here to avoid circular imports
            from app.services.chat_service import ChatService
            from app.models.hub_item import HubItem
            from app.models.planning import DEFAULT_GROUP_SLUG, Group
            from sqlalchemy import select
            
            # Fetch recent messages
            chat_service = ChatService(self.db)
            # Strip tz before querying the naive TIMESTAMP WITHOUT TIME ZONE column
            cutoff = start_at or (datetime.now(timezone.utc) - timedelta(hours=hours)).replace(tzinfo=None)
            recent_messages = await chat_service.get_recent_messages(
                limit=max_messages,
                start_at=cutoff,
                end_at=end_at,
                room_id=room_id,
            )
            
            if not recent_messages:
                result = {
                    "summary": "No recent messages to summarize.",
                    "memories_created": 0,
                    "suggestions_created": 0,
                    "memory_entries": [],
                    "suggestions": [],
                }
                if run:
                    duration_ms = int((time.monotonic() - start_time) * 1000)
                    await self.run_repo.update(
                        run_id=run.id,
                        status="completed",
                        raw_response="",
                        parsed_response={"summary": result["summary"]},
                        duration_ms=duration_ms,
                    )
                return result
            
            # Message-ID range covered by this summary (for catchup/timeline links)
            msg_ids = [m["id"] for m in recent_messages if m.get("id") is not None]
            message_start_id = min(msg_ids) if msg_ids else None
            message_end_id = max(msg_ids) if msg_ids else None

            # Build messages text bundle
            messages_text = self._build_messages_text(recent_messages)
            
            # Fetch active hub items for context
            hub_items_text = await self._build_hub_items_text()
            
            # Fetch existing relevant memories for context
            existing_memories_text = await self._build_existing_memories_text()
            
            # Update run with prompt text
            prompt_text = f"MESSAGES:\n{messages_text}\n\nHUB ITEMS:\n{hub_items_text}\n\nEXISTING MEMORIES:\n{existing_memories_text}"
            if run:
                await self.run_repo.update(
                    run_id=run.id,
                    prompt_text=prompt_text,
                )
            
            # Call LLM client
            result = await self.llm_client.generate_summary(
                messages_text,
                hub_items_text,
                existing_memories_text,
            )
            
            duration_ms = int((time.monotonic() - start_time) * 1000)
            
            # Store memory entries (unless dry_run)
            memory_entries = []
            memory_ids = []
            if not dry_run:
                for mem_data in result.get("memories", []):
                    entry = await self.memory_repo.create(
                        memory_type=mem_data["type"],
                        title=mem_data.get("title"),
                        content=mem_data["content"],
                        tags=mem_data.get("tags", []),
                        confidence=mem_data.get("confidence"),
                        source_type="chat",
                        created_by=created_by,
                        room_id=room_id,
                        message_start_id=message_start_id,
                        message_end_id=message_end_id,
                    )
                    memory_entries.append(entry)
                    memory_ids.append(str(entry.id))
            else:
                # In dry_run mode, create dummy entries for the response
                for mem_data in result.get("memories", []):
                    memory_entries.append({
                        "type": mem_data["type"],
                        "title": mem_data.get("title"),
                        "content": mem_data["content"],
                        "tags": mem_data.get("tags", []),
                        "confidence": mem_data.get("confidence"),
                    })
            
            # Store suggestions (unless dry_run)
            suggestions = []
            if not dry_run:
                for sug_data in result.get("suggestions", []):
                    suggestion = await self.suggestion_repo.create(
                        suggestion_type=sug_data["type"],
                        title=sug_data["title"],
                        body=sug_data.get("body"),
                        proposed_hub_item_type=sug_data.get("hub_item_type"),
                        proposed_payload=sug_data.get("payload"),
                        source_memory_ids=memory_ids,
                    )
                    suggestions.append(suggestion)
            else:
                # In dry_run mode, create dummy entries for the response
                for sug_data in result.get("suggestions", []):
                    suggestions.append({
                        "type": sug_data["type"],
                        "title": sug_data["title"],
                        "body": sug_data.get("body"),
                        "hub_item_type": sug_data.get("hub_item_type"),
                        "payload": sug_data.get("payload"),
                    })
            
            response_data = {
                "summary": result.get("summary", ""),
                "memories_created": len(memory_entries),
                "suggestions_created": len(suggestions),
                "memory_entries": memory_entries,
                "suggestions": suggestions,
            }
            
            # Update run record
            if run:
                await self.run_repo.mark_completed(
                    run_id=run.id,
                    raw_response=str(result),
                    parsed_response=result,
                    created_memory_ids=memory_ids if not dry_run else None,
                    created_suggestion_ids=[str(s.id) for s in suggestions] if not dry_run else None,
                    duration_ms=duration_ms,
                )
                response_data["agent_run_id"] = str(run.id)
            
            return response_data
            
        except Exception as e:
            logger.error("Error in summarize_chat: %s", e)
            duration_ms = int((time.monotonic() - start_time) * 1000)
            
            if run:
                await self.run_repo.mark_failed(
                    run_id=run.id,
                    error_message=str(e),
                    duration_ms=duration_ms,
                )
            
            raise

    def _build_messages_text(self, messages: List[dict]) -> str:
        """Build a deterministic text bundle from messages."""
        lines = []
        for msg in messages:
            if msg.get("is_deleted"):
                continue
            nickname = msg.get("nickname", "Unknown")
            content = msg.get("content", "")
            created_at = msg.get("created_at", "")
            lines.append(f"[{created_at}] {nickname}: {content}")
        return "\n".join(lines)

    async def _build_hub_items_text(self) -> str:
        """Build a text bundle of active hub items."""
        from app.models.hub_item import HubItem
        from app.models.planning import DEFAULT_GROUP_SLUG, Group
        from sqlalchemy import select
        
        # Get default group
        result = await self.db.execute(
            select(Group).where(Group.slug == DEFAULT_GROUP_SLUG)
        )
        group = result.scalar_one_or_none()
        if not group:
            return "(no hub items)"
        
        # Fetch active hub items
        stmt = (
            select(HubItem)
            .where(HubItem.group_id == group.id)
            .where(HubItem.status != "archived")
            .order_by(HubItem.updated_at.desc())
            .limit(20)
        )
        result = await self.db.execute(stmt)
        items = result.scalars().all()
        
        if not items:
            return "(no active hub items)"
        
        lines = []
        for item in items:
            lines.append(f"- {item.short_id} [{item.item_type}]: {item.title}")
            if item.body:
                lines.append(f"  {item.body[:100]}")
            if item.due_at:
                lines.append(f"  Due: {item.due_at}")
        
        return "\n".join(lines)

    async def _build_existing_memories_text(self) -> str:
        """Build a text bundle of recent relevant memories."""
        memories = await self.memory_repo.list_recent(limit=10)
        
        if not memories:
            return ""
        
        lines = []
        for mem in memories:
            lines.append(f"- [{mem.memory_type}] {mem.title or 'Untitled'}: {mem.content[:100]}")
        
        return "\n".join(lines)


# ── Factory function ──────────────────────────────────────────────────────────


def create_llm_client(provider: str = None) -> LLMClient:
    """Create an LLM client based on configuration.
    
    This factory reuses the existing OpenRouter configuration from the Hub Bot
    when provider is "openrouter". It supports:
    - "fake": FakeLLMClient for testing
    - "ollama": OllamaLLMClient for local inference
    - "openrouter": OpenRouterLLMClient (reuses existing gateway config)
    
    Args:
        provider: Provider name. Defaults to config.ai_lab_provider.
        
    Returns:
        Configured LLMClient instance
    """
    provider = provider or settings.ai_lab_provider
    
    if provider == "ollama":
        return OllamaLLMClient()
    
    if provider == "openrouter":
        if not settings.ai_api_key:
            logger.warning("OpenRouter API key not configured, falling back to FakeLLMClient")
            return FakeLLMClient()
        return OpenRouterLLMClient()

    # provider == "fake" (default) — auto-upgrade to OpenRouter when key is available
    if settings.ai_api_key:
        logger.info(
            "ai_lab_provider=fake but AI_API_KEY is configured; auto-selecting openrouter for Lab"
        )
        return OpenRouterLLMClient()

    return FakeLLMClient()


def create_summary_service(
    db: AsyncSession,
    use_fake_llm: bool = True,
    llm_client: Optional[LLMClient] = None,
) -> HubSummaryService:
    """Create a HubSummaryService with the appropriate LLM client.
    
    Args:
        db: Database session
        use_fake_llm: If True, use FakeLLMClient. If False, use configured provider.
        llm_client: Optional explicit LLM client to use.
        
    Returns:
        Configured HubSummaryService
    """
    if llm_client:
        client = llm_client
    elif use_fake_llm:
        client = FakeLLMClient()
    else:
        client = create_llm_client()
    
    return HubSummaryService(db, client)
