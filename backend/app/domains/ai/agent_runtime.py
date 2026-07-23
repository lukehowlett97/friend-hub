"""
Hub Agent Runtime — lightweight tool-aware conversational agent.

The LLM receives:
- world snapshot (active hub items)
- relevant memories
- recent chat messages
- available tools with descriptions and schemas

The LLM returns structured JSON:
- reply: conversational response
- tool_calls: optional tools to execute (read_only or safe_write)
- memories: optional memory entries to store
- suggestions: optional suggestions to create

Tool execution is bounded at two passes: when the first pass calls only
read-only tools (search/lookup), the results are fed back for one follow-up
completion so the reply can use them. The second pass may only execute write
tools — no recursive tool loops.
"""
import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.ai.capabilities import build_capabilities_prompt
from app.domains.ai.tools import ToolRegistry, build_default_registry
from app.domains.ai.summary_service import LLMClient, FakeLLMClient
from app.domains.ai.repository import AIMemoryRepository, AISuggestionRepository

logger = logging.getLogger(__name__)


# ── Data Models ───────────────────────────────────────────────────────────────


@dataclass
class AgentRuntimeResult:
    """Result of a tool-aware agent run."""
    reply: str
    tool_results: List[Dict[str, Any]] = field(default_factory=list)
    created_memories: int = 0
    created_suggestions: int = 0
    validation_errors: List[str] = field(default_factory=list)
    tool_calls_attempted: int = 0
    raw_response: str = ""
    # UUIDs (as strings) of ai_draft_actions rows created during this run.
    # Populated from successful propose_* tool results; never from LLM text.
    proposed_draft_action_ids: List[str] = field(default_factory=list)


# ── System Prompt Template ────────────────────────────────────────────────────


_SYSTEM_PROMPT_TEMPLATE = """You are Hub Bot, a friendly assistant inside Friend Hub.
You help friends organise their social lives — events, polls, reminders, and general planning.

Current UTC time: {current_utc}

═══════════════════════════════════════════
YOUR CAPABILITIES
═══════════════════════════════════════════

{capabilities}

Output ONLY a single valid JSON object — no markdown, no code fences, no text before or after.
The JSON must have exactly these four keys:

{{
    "reply": "Your conversational reply here",
    "tool_calls": [],
    "memories": [],
    "suggestions": []
}}

═══════════════════════════════════════════
SLASH COMMANDS — ACT IMMEDIATELY
═══════════════════════════════════════════

When the user message starts with /event, /poll, /remind, or /idea:
- Call the tool immediately with the information given.
- Do NOT ask clarifying questions.
- Resolve relative times ("tonight", "tomorrow", "next Friday", "7pm") using the current UTC time above.
- If a detail is truly missing (e.g. no title at all), make a sensible assumption.
- /event  → propose_event
- /poll   → propose_poll
- /remind → propose_reminder
- /idea   → propose_idea

═══════════════════════════════════════════
TOOL CALL FORMAT — READ THIS CAREFULLY
═══════════════════════════════════════════

Every entry in "tool_calls" must be an object with exactly two keys:
  "tool"      — the tool name (string, required)
  "arguments" — an object of named parameters (required, can be {{}})

CORRECT example — create a poll:
{{
  "reply": "Poll created!",
  "tool_calls": [
    {{
      "tool": "propose_poll",
      "arguments": {{
        "question": "What should we do this weekend?",
        "options": ["Pub", "Cinema", "House party"],
        "closes_at": "2026-05-17T23:59:00Z"
      }}
    }}
  ],
  "memories": [],
  "suggestions": []
}}

CORRECT example — create an event with a relative time ("tonight at 7pm" when current UTC is 2026-05-17T14:00:00Z):
{{
  "reply": "Event created!",
  "tool_calls": [
    {{
      "tool": "propose_event",
      "arguments": {{
        "title": "Bean Party",
        "starts_at": "2026-05-17T19:00:00Z"
      }}
    }}
  ],
  "memories": [],
  "suggestions": []
}}

CORRECT example — create a reminder with full context:
{{
  "reply": "Reminder set!",
  "tool_calls": [
    {{
      "tool": "propose_reminder",
      "arguments": {{
        "title": "Book taxis",
        "context": "User asked to be reminded to book taxis before Friday night out.",
        "remind_at": "2026-05-15T18:00:00Z"
      }}
    }}
  ],
  "memories": [],
  "suggestions": []
}}

REMINDER BEST PRACTICE:
- "title" should be a short, clear subject (5 words or fewer).
- "context" should be a plain-English sentence explaining WHY or WHAT the reminder is for, using any extra detail from the user's message. Always populate context if there is any meaningful detail beyond just the title.
- For repeating reminders, set "recurrence" to "daily", "weekly", or "every_N_days"; include "recurrence_days" for every_N_days and "recurrence_ends_at" if the user gives an end date.

REFERENCE TAG BEST PRACTICE:
- When creating any poll, event, reminder, or idea, include "reference_tag" with a short semantic slug based on the item, such as "party", "book-taxis", or "dinner-vote".
- Do not include the leading # or item prefix unless the user explicitly gave one. The server will add the correct type prefix (#E-*, #P-*, #R-*, #I-*) and will make the tag unique if needed.
- Keep it memorable, lowercase, and 1-3 words joined with hyphens.

WRONG — do NOT put tool arguments at the top level of the tool_calls entry:
{{
  "tool_calls": [
    {{
      "tool": "propose_poll",
      "question": "...",
      "options": [...]
    }}
  ]
}}

WRONG — do NOT use "name" instead of "tool":
{{
  "tool_calls": [{{ "name": "propose_poll", "arguments": {{...}} }}]
}}

WRONG — do NOT omit the "tool" key entirely:
{{
  "tool_calls": [{{ "arguments": {{...}} }}]
}}

═══════════════════════════════════════════
AVAILABLE TOOLS
═══════════════════════════════════════════

{tools_json}

═══════════════════════════════════════════
RULES
═══════════════════════════════════════════

1. Slash commands (/event, /poll, /remind, /idea): call the tool immediately. No questions.
2. To create a poll, event, or reminder — use the matching propose_* tool.
   Do NOT describe what you would do; actually call the tool.
3. Only say "I've created..." in your reply AFTER you have included the tool call.
   If you are not calling a tool, do not claim you are creating anything.
4. Set "tool_calls" to [] when no tool is needed.
5. Keep replies short — one sentence is usually enough after a slash command.
6. Reference Hub Items by exact short ID (e.g. #P-1, #E-3).
7. All datetimes must be ISO-8601 with UTC timezone (e.g. 2026-05-21T19:00:00Z).
   Resolve relative times using the current UTC time shown at the top.

CONTEXT:
{context}

USER MESSAGE: {user_message}
"""


_FOLLOWUP_PROMPT_TEMPLATE = """You are Hub Bot, a friendly assistant inside Friend Hub.
You previously decided to look up information before answering. The lookups have
been executed and their results are below. Now write your final reply using them.

Current UTC time: {current_utc}

Output ONLY a single valid JSON object with exactly these four keys:

{{
    "reply": "Your conversational reply here",
    "tool_calls": [],
    "memories": [],
    "suggestions": []
}}

RULES:
1. Answer the user from the TOOL RESULTS below. If they are empty or unhelpful,
   say you couldn't find anything — do not invent details.
2. Do NOT call read-only/search tools again — you already have the results.
3. Only include tool_calls if you now need to create something (propose_*),
   using the same {{"tool": ..., "arguments": {{...}}}} format as before.
4. Keep the reply short and conversational. Reference items by exact short ID
   (e.g. #P-1, #E-3).

CONTEXT:
{context}

USER MESSAGE: {user_message}

YOUR TOOL CALLS AND THEIR RESULTS:
{tool_results_json}
"""


# ── Agent Runtime ─────────────────────────────────────────────────────────────


class HubAgentRuntime:
    """Lightweight tool-aware conversational agent.
    
    Single-pass architecture:
    User message → LLM (with tools context) → structured JSON → tool execution → response
    
    No recursive loops, no autonomous planning, no agent frameworks.
    """

    def __init__(
        self,
        db: AsyncSession,
        llm_client: Optional[LLMClient] = None,
        registry: Optional[ToolRegistry] = None,
        tool_context: Optional[Dict[str, Any]] = None,
    ):
        self.db = db
        self.llm_client = llm_client or FakeLLMClient()
        self.registry = registry or build_default_registry()
        self.memory_repo = AIMemoryRepository(db)
        self.suggestion_repo = AISuggestionRepository(db)
        # Server-side context forwarded to tools that declare a _ctx parameter.
        # Callers (hub_agent_service) inject group_id, created_by_user_id, etc.
        # The LLM cannot supply or override these values.
        self._tool_context: Dict[str, Any] = tool_context or {}

    async def run(
        self,
        user_message: str,
        context: str = "",
        dry_run: bool = False,
    ) -> AgentRuntimeResult:
        """Run the agent: build prompt, call LLM, execute tools, return result.
        
        Args:
            user_message: The user's query
            context: World snapshot + recent messages + memories bundle
            dry_run: If True, execute tools but don't save results
            
        Returns:
            AgentRuntimeResult with reply and metadata
        """
        # Get available tools from registry
        tools_with_handlers = self.registry.list_tools()
        tools_json = json.dumps(tools_with_handlers, indent=2)
        
        # Build the prompt with tool descriptions
        from datetime import datetime, timezone
        current_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        prompt = _SYSTEM_PROMPT_TEMPLATE.format(
            tools_json=tools_json,
            context=context or "(no additional context)",
            user_message=user_message,
            current_utc=current_utc,
            capabilities=build_capabilities_prompt(),
        )
        
        # Call the LLM
        try:
            if isinstance(self.llm_client, FakeLLMClient):
                raw_response = await self._call_fake_llm(user_message, context)
            else:
                raw_response = await self._call_real_llm(prompt)
        except Exception as e:
            logger.error("LLM call failed: %s", e)
            return AgentRuntimeResult(
                reply="Sorry, I hit an error. Please try again.",
                raw_response="",
            )
        
        # Parse the response
        parsed = self._parse_response(raw_response)
        
        # Execute tool calls (pass 1)
        tool_results = []
        validation_errors = list(parsed.get("validation_errors", []))
        tool_calls_attempted = len(parsed.get("tool_calls", []))

        for tc in parsed.get("tool_calls", []):
            tool_name = tc.get("tool", "")
            args = tc.get("arguments", {})
            result = await self._execute_tool(tool_name, args, dry_run)
            tool_results.append(result)

        # ── Pass 2: feed read-only results back to the model ─────────────────
        # In a single pass, read tools are useless — the model asks for data it
        # never gets to see. When pass 1 called only read-only tools, run one
        # follow-up completion with the results so the reply can use them.
        # Pass 2 may only execute write tools; there is no third pass.
        if (
            tool_results
            and not isinstance(self.llm_client, FakeLLMClient)
            and all(self._is_read_only(tr.get("tool", "")) for tr in tool_results)
        ):
            followup_prompt = _FOLLOWUP_PROMPT_TEMPLATE.format(
                current_utc=current_utc,
                context=context or "(no additional context)",
                user_message=user_message,
                tool_results_json=json.dumps(tool_results, indent=2, default=str),
            )
            try:
                raw_followup = await self._call_real_llm(followup_prompt)
                parsed_followup = self._parse_response(raw_followup)
                validation_errors.extend(parsed_followup.get("validation_errors", []))
                tool_calls_attempted += len(parsed_followup.get("tool_calls", []))

                for tc in parsed_followup.get("tool_calls", []):
                    tool_name = tc.get("tool", "")
                    if self._is_read_only(tool_name):
                        tool_results.append({
                            "tool": tool_name,
                            "success": False,
                            "skipped": True,
                            "reason": "Read-only tools are limited to the first pass.",
                        })
                        continue
                    result = await self._execute_tool(
                        tool_name, tc.get("arguments", {}), dry_run
                    )
                    tool_results.append(result)

                # The follow-up supersedes pass 1: its reply replaces the
                # placeholder, and its memories/suggestions replace pass 1's
                # so nothing is saved twice.
                parsed = parsed_followup
                raw_response = f"{raw_response}\n--- second pass ---\n{raw_followup}"
            except Exception as e:
                logger.warning("Second-pass LLM call failed, keeping first reply: %s", e)

        # Create memories (unless dry run)
        created_memories = 0
        for mem in parsed.get("memories", []):
            if dry_run:
                created_memories += 1
                continue
            try:
                entry = await self.memory_repo.create(
                    memory_type=mem.get("type", "daily_summary"),
                    title=mem.get("title"),
                    content=mem.get("content", ""),
                    tags=mem.get("tags", []),
                    confidence=mem.get("confidence"),
                    source_type="chat",
                )
                if entry:
                    created_memories += 1
            except Exception as e:
                validation_errors.append(f"Failed to create memory: {e}")
        
        # Create suggestions (unless dry run)
        created_suggestions = 0
        for sug in parsed.get("suggestions", []):
            if dry_run:
                created_suggestions += 1
                continue
            try:
                suggestion = await self.suggestion_repo.create(
                    suggestion_type=sug.get("type", "summary"),
                    title=sug.get("title", "Untitled"),
                    body=sug.get("body"),
                    proposed_hub_item_type=sug.get("hub_item_type"),
                    proposed_payload=sug.get("payload"),
                    source_memory_ids=[],
                )
                if suggestion:
                    created_suggestions += 1
            except Exception as e:
                validation_errors.append(f"Failed to create suggestion: {e}")
        
        # Collect legacy draft_action_id values from successful propose_* tool results.
        # Current propose_* tools create final items immediately and usually do
        # not return draft IDs. Keep this for older tool implementations.
        proposed_draft_action_ids: List[str] = []
        successful_propose = False
        for tr in tool_results:
            if not tr.get("success"):
                continue
            inner = tr.get("result", {})
            if isinstance(inner, dict) and inner.get("success"):
                if tr.get("tool", "").startswith("propose_"):
                    successful_propose = True
                if inner.get("draft_action_id"):
                    proposed_draft_action_ids.append(str(inner["draft_action_id"]))

        # ── Reply integrity check ─────────────────────────────────────────────
        # If the model claimed to have drafted/created something but every tool
        # call failed, replace the reply so the user isn't misled.
        reply = parsed.get("reply", "I processed your request.")
        _DRAFT_CLAIM_PHRASES = (
            "i've drafted", "i have drafted", "i've created", "i have created",
            "draft is ready", "here is the draft", "here's the draft",
            "i've set up", "i have set up", "i've proposed", "i have proposed",
        )
        # "attempted_propose" is True when a known propose_* tool was called,
        # or when a malformed tool call likely tried to create something while
        # the reply claimed creation.
        attempted_propose = (
            any(tr.get("tool", "").startswith("propose_") for tr in tool_results)
            or (bool(tool_results) and not successful_propose)
        )
        all_propose_failed = attempted_propose and not successful_propose
        if all_propose_failed:
            lower_reply = reply.lower()
            if any(phrase in lower_reply for phrase in _DRAFT_CLAIM_PHRASES):
                logger.warning(
                    "Suppressing false draft claim in reply — tool calls failed"
                )
                reply = (
                    "I tried to create a draft but something went wrong with the tool call. "
                    "Please try again or rephrase your request."
                )

        return AgentRuntimeResult(
            reply=reply,
            tool_results=tool_results,
            created_memories=created_memories,
            created_suggestions=created_suggestions,
            validation_errors=validation_errors,
            tool_calls_attempted=tool_calls_attempted,
            raw_response=raw_response,
            proposed_draft_action_ids=proposed_draft_action_ids,
        )

    def _is_read_only(self, tool_name: str) -> bool:
        """True when the tool is registered with read_only safety."""
        tool = self.registry.get(tool_name)
        return bool(tool) and tool.get("safety") == "read_only"

    async def _call_fake_llm(self, user_message: str, context: str) -> str:
        """Call the FakeLLMClient and convert to agent-compatible format."""
        result = await self.llm_client.generate_summary(
            messages_text=user_message,
            hub_items_text=context,
        )
        # Build the expected JSON structure
        response = {
            "reply": result.get("summary", "Response generated."),
            "tool_calls": [],
            "memories": result.get("memories", []),
            "suggestions": result.get("suggestions", []),
        }
        return json.dumps(response)

    async def _call_real_llm(self, prompt: str) -> str:
        """Call a real LLM (OpenRouter/Ollama) with the tool-aware prompt."""
        messages = [
            {"role": "system", "content": "You are a helpful assistant. Output ONLY valid JSON."},
            {"role": "user", "content": prompt},
        ]
        
        if hasattr(self.llm_client, '_get_provider'):
            # OpenRouter path
            provider = self.llm_client._get_provider()
            model = self.llm_client.model
            response_text, _, _ = await provider.complete_chat(messages, model)
            return response_text
        elif hasattr(self.llm_client, 'generate_summary'):
            # Ollama/Fake path
            import httpx
            from app.config import get_settings
            settings = get_settings()
            payload = {
                "model": settings.ollama_model,
                "prompt": prompt,
                "system": "You are a helpful assistant. Output ONLY valid JSON.",
                "stream": False,
                "format": "json",
            }
            async with httpx.AsyncClient(timeout=float(settings.ollama_timeout)) as client:
                resp = await client.post(
                    f"{settings.ollama_base_url}/api/generate",
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()
                return data.get("response", "")
        
        return json.dumps({"reply": "Response generated.", "tool_calls": [], "memories": [], "suggestions": []})

    def _parse_response(self, raw: str) -> dict:
        """Parse and validate the LLM JSON response.
        
        Graceful fallback: if JSON is invalid, return conversational text only.
        """
        if not raw:
            return {"reply": "I received your message.", "tool_calls": [], "memories": [], "suggestions": [], "validation_errors": ["Empty response"]}
        
        # Try to extract JSON from the response
        json_match = re.search(r'\{[\s\S]*\}', raw)
        if not json_match:
            logger.warning("No JSON found in LLM response")
            return {"reply": raw[:1000], "tool_calls": [], "memories": [], "suggestions": [], "validation_errors": ["No JSON found in response"]}
        
        try:
            data = json.loads(json_match.group())
        except json.JSONDecodeError as e:
            logger.warning("Invalid JSON in LLM response: %s", e)
            return {"reply": raw[:1000], "tool_calls": [], "memories": [], "suggestions": [], "validation_errors": [f"JSON parse error: {e}"]}
        
        # Validate structure
        if not isinstance(data, dict):
            return {"reply": raw[:1000], "tool_calls": [], "memories": [], "suggestions": [], "validation_errors": ["Response is not a JSON object"]}
        
        errors = []
        if "reply" not in data:
            errors.append("Missing 'reply' field")
            data["reply"] = "I processed your request."
        
        if not isinstance(data.get("tool_calls", []), list):
            errors.append("'tool_calls' must be a list")
            data["tool_calls"] = []
        
        if not isinstance(data.get("memories", []), list):
            errors.append("'memories' must be a list")
            data["memories"] = []
        
        if not isinstance(data.get("suggestions", []), list):
            errors.append("'suggestions' must be a list")
            data["suggestions"] = []
        
        data["validation_errors"] = errors

        # ── Normalise and validate individual tool calls ──────────────────────
        # Models occasionally use "name" instead of "tool" (OpenAI convention),
        # or flatten arguments to the top level of the entry.  We normalise
        # these common mistakes before validation so execution can still succeed.
        #
        # Known propose_* tool names for safe flat-argument promotion.
        _KNOWN_TOOLS = {
            "propose_poll", "propose_event", "propose_reminder", "propose_idea",
            "get_item_by_reference", "search_hub_items", "list_recent_hub_items",
            "search_memories", "list_recent_memories", "list_pending_suggestions",
            "create_memory_entry", "create_ai_suggestion",
        }
        # Per-tool: which top-level keys are valid arguments (not structural keys).
        _STRUCTURAL_KEYS = {"tool", "name", "arguments"}

        for i, tc in enumerate(data.get("tool_calls", [])):
            if not isinstance(tc, dict):
                errors.append(f"tool_calls[{i}] is not an object")
                continue

            # Normalise "name" → "tool"
            if "tool" not in tc and "name" in tc:
                tc["tool"] = tc.pop("name")

            tool_name = tc.get("tool", "")

            # If arguments are missing or not a dict, check for flat promotion.
            # Only promote when the tool name is known, to avoid misattribution.
            if ("arguments" not in tc or not isinstance(tc.get("arguments"), dict)):
                flat_args = {k: v for k, v in tc.items() if k not in _STRUCTURAL_KEYS}
                if flat_args and tool_name in _KNOWN_TOOLS:
                    tc["arguments"] = flat_args
                    errors.append(
                        f"tool_calls[{i}] arguments were at wrong level — promoted automatically"
                    )
                else:
                    tc["arguments"] = {}

            if not tool_name:
                errors.append(f"tool_calls[{i}] missing 'tool' field")
        
        # Validate individual memories
        for i, mem in enumerate(data.get("memories", [])):
            if "type" not in mem:
                errors.append(f"memories[{i}] missing 'type' field")
            if "content" not in mem:
                errors.append(f"memories[{i}] missing 'content' field")
        
        # Validate individual suggestions
        for i, sug in enumerate(data.get("suggestions", [])):
            if "type" not in sug:
                errors.append(f"suggestions[{i}] missing 'type' field")
            if "title" not in sug:
                errors.append(f"suggestions[{i}] missing 'title' field")
        
        return data

    async def _execute_tool(self, tool_name: str, arguments: dict, dry_run: bool) -> dict:
        """Execute a single tool call.
        
        read_only tools: always executed (but not saved in dry_run)
        safe_write tools: executed in non-dry-run mode only
        approval_required tools: NOT executed directly
        """
        tool = self.registry.get(tool_name)
        if not tool:
            return {"tool": tool_name, "success": False, "error": f"Tool '{tool_name}' not found"}
        
        safety = tool.get("safety", "read_only")
        
        if safety == "approval_required":
            return {
                "tool": tool_name,
                "success": False,
                "skipped": True,
                "reason": "This tool requires approval. A suggestion has been created.",
            }
        
        if safety == "safe_write" and dry_run:
            return {
                "tool": tool_name,
                "success": False,
                "skipped": True,
                "reason": "Write tools are disabled in dry run mode.",
            }
        
        try:
            # Merge server-side context with current dry_run flag.
            # Tools that accept _ctx receive it; others ignore it.
            ctx = {**self._tool_context, "dry_run": dry_run}
            result = await self.registry.call(tool_name, self.db, _ctx=ctx, **arguments)
            return {
                "tool": tool_name,
                "success": True,
                "result": result,
                "safety": safety,
            }
        except Exception as e:
            logger.error("Tool %s failed: %s", tool_name, e)
            return {
                "tool": tool_name,
                "success": False,
                "error": str(e),
            }
